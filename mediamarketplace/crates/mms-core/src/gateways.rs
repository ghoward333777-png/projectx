//! Payment gateways. The server never sees card numbers: every gateway redirects
//! to its own hosted page and reports back through a return URL and webhooks.

use anyhow::{bail, Context, Result};
use async_trait::async_trait;
use hmac::{Hmac, Mac};
use serde::{Deserialize, Serialize};
use sha2::Sha256;

/// What checkout needs from a gateway to send the customer off to pay.
#[derive(Debug, Clone, Serialize)]
pub struct Started {
    pub redirect_url: String,
    pub external_id: String,
}

/// Facts about the order the gateway needs.
#[derive(Debug, Clone)]
pub struct OrderFacts {
    pub uuid: String,
    pub number: String,
    pub currency: String,
    pub total_cents: i64,
    pub customer_email: String,
    pub lines: Vec<(String, i64, i64)>, // title, unit cents, quantity
    /// Set for a recurring site pass: (interval, product title).
    pub recurring: Option<(String, String)>,
    pub success_url: String,
    pub cancel_url: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Outcome {
    Paid {
        external_id: String,
        subscription_id: Option<String>,
        period_end: Option<String>,
    },
    Pending,
    Failed(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Event {
    /// A checkout finished: (our order uuid if known, gateway reference).
    Paid {
        order_uuid: Option<String>,
        external_id: String,
        subscription_id: Option<String>,
        period_end: Option<String>,
    },
    Refunded {
        external_id: String,
    },
    SubscriptionRenewed {
        subscription_id: String,
        period_end: String,
    },
    SubscriptionEnded {
        subscription_id: String,
    },
    Ignored(String),
}

#[async_trait]
pub trait Gateway: Send + Sync {
    fn name(&self) -> &'static str;
    fn label(&self) -> &'static str;
    async fn start(&self, order: &OrderFacts) -> Result<Started>;
    /// Called when the customer returns; `params` are the query string values.
    async fn confirm(
        &self,
        order: &OrderFacts,
        external_id: &str,
        params: &[(String, String)],
    ) -> Result<Outcome>;
    /// Parses and verifies a webhook. Returns (event id, event).
    async fn webhook(&self, headers: &[(String, String)], body: &[u8]) -> Result<(String, Event)>;
    async fn refund(&self, external_id: &str, amount_cents: i64, currency: &str) -> Result<String>;
    async fn cancel_subscription(&self, subscription_id: &str, at_period_end: bool) -> Result<()>;
}

// ----- test gateway: completes on a local page; for development and demos -----

pub struct TestGateway {
    pub base_url: String,
}

#[async_trait]
impl Gateway for TestGateway {
    fn name(&self) -> &'static str {
        "test"
    }
    fn label(&self) -> &'static str {
        "Test payment (no money moves)"
    }
    async fn start(&self, order: &OrderFacts) -> Result<Started> {
        Ok(Started {
            redirect_url: format!("{}/checkout/test/{}", self.base_url, order.uuid),
            external_id: format!("test_{}", order.uuid),
        })
    }
    async fn confirm(
        &self,
        order: &OrderFacts,
        external_id: &str,
        params: &[(String, String)],
    ) -> Result<Outcome> {
        let result = params
            .iter()
            .find(|(k, _)| k == "result")
            .map(|(_, v)| v.as_str())
            .unwrap_or("paid");
        Ok(match result {
            "paid" => Outcome::Paid {
                external_id: external_id.to_string(),
                subscription_id: order
                    .recurring
                    .as_ref()
                    .map(|_| format!("sub_test_{}", order.uuid)),
                period_end: order.recurring.as_ref().map(|(i, _)| {
                    crate::commerce::add_days(&crate::now(), if i == "year" { 366 } else { 31 })
                }),
            },
            "fail" => Outcome::Failed("Declined by the test gateway".into()),
            _ => Outcome::Pending,
        })
    }
    async fn webhook(&self, _headers: &[(String, String)], body: &[u8]) -> Result<(String, Event)> {
        #[derive(Deserialize)]
        struct Hook {
            id: String,
            kind: String,
            #[serde(default)]
            order_uuid: Option<String>,
            #[serde(default)]
            external_id: String,
            #[serde(default)]
            subscription_id: Option<String>,
            #[serde(default)]
            period_end: Option<String>,
        }
        let h: Hook = serde_json::from_slice(body).context("test webhook body")?;
        let ev = match h.kind.as_str() {
            "paid" => Event::Paid {
                order_uuid: h.order_uuid,
                external_id: h.external_id,
                subscription_id: h.subscription_id,
                period_end: h.period_end,
            },
            "refunded" => Event::Refunded {
                external_id: h.external_id,
            },
            "renewed" => Event::SubscriptionRenewed {
                subscription_id: h.subscription_id.unwrap_or_default(),
                period_end: h.period_end.unwrap_or_default(),
            },
            "ended" => Event::SubscriptionEnded {
                subscription_id: h.subscription_id.unwrap_or_default(),
            },
            other => Event::Ignored(other.to_string()),
        };
        Ok((h.id, ev))
    }
    async fn refund(
        &self,
        external_id: &str,
        _amount_cents: i64,
        _currency: &str,
    ) -> Result<String> {
        Ok(format!("re_{external_id}"))
    }
    async fn cancel_subscription(
        &self,
        _subscription_id: &str,
        _at_period_end: bool,
    ) -> Result<()> {
        Ok(())
    }
}

// ----- Stripe: Checkout Sessions, Billing for recurring passes, signed webhooks -----

pub struct Stripe {
    pub secret_key: String,
    pub webhook_secret: String,
    pub http: reqwest::Client,
}

impl Stripe {
    pub fn new(secret_key: &str, webhook_secret: &str) -> Self {
        Self {
            secret_key: secret_key.into(),
            webhook_secret: webhook_secret.into(),
            http: reqwest::Client::new(),
        }
    }

    async fn post(&self, path: &str, form: &[(String, String)]) -> Result<serde_json::Value> {
        let res = self
            .http
            .post(format!("https://api.stripe.com/v1/{path}"))
            .basic_auth(&self.secret_key, None::<&str>)
            .form(form)
            .send()
            .await
            .context("Stripe request failed")?;
        let status = res.status();
        let v: serde_json::Value = res.json().await.context("Stripe reply was not JSON")?;
        if !status.is_success() {
            bail!(
                "Stripe: {}",
                v["error"]["message"].as_str().unwrap_or("request refused")
            );
        }
        Ok(v)
    }

    async fn get(&self, path: &str) -> Result<serde_json::Value> {
        let res = self
            .http
            .get(format!("https://api.stripe.com/v1/{path}"))
            .basic_auth(&self.secret_key, None::<&str>)
            .send()
            .await
            .context("Stripe request failed")?;
        let status = res.status();
        let v: serde_json::Value = res.json().await.context("Stripe reply was not JSON")?;
        if !status.is_success() {
            bail!(
                "Stripe: {}",
                v["error"]["message"].as_str().unwrap_or("request refused")
            );
        }
        Ok(v)
    }

    /// Verifies a `Stripe-Signature` header against the raw body. Pure, testable.
    pub fn verify_signature(
        secret: &str,
        header: &str,
        body: &[u8],
        now_unix: i64,
        tolerance: i64,
    ) -> Result<()> {
        let mut ts = None;
        let mut sigs = Vec::new();
        for part in header.split(',') {
            let (k, v) = part.trim().split_once('=').unwrap_or(("", ""));
            match k {
                "t" => ts = v.parse::<i64>().ok(),
                "v1" => sigs.push(v.to_string()),
                _ => {}
            }
        }
        let ts = ts.context("signature header has no timestamp")?;
        if (now_unix - ts).abs() > tolerance {
            bail!("webhook timestamp outside tolerance");
        }
        let mut mac = Hmac::<Sha256>::new_from_slice(secret.as_bytes()).context("bad secret")?;
        mac.update(ts.to_string().as_bytes());
        mac.update(b".");
        mac.update(body);
        let expected = hex(&mac.finalize().into_bytes());
        if sigs.iter().any(|s| constant_eq(s, &expected)) {
            Ok(())
        } else {
            bail!("webhook signature mismatch")
        }
    }
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn constant_eq(a: &str, b: &str) -> bool {
    a.len() == b.len()
        && a.bytes()
            .zip(b.bytes())
            .fold(0u8, |acc, (x, y)| acc | (x ^ y))
            == 0
}

fn unix_to_iso(secs: i64) -> String {
    chrono::DateTime::<chrono::Utc>::from_timestamp(secs, 0)
        .map(|d| d.format("%Y-%m-%dT%H:%M:%SZ").to_string())
        .unwrap_or_default()
}

#[async_trait]
impl Gateway for Stripe {
    fn name(&self) -> &'static str {
        "stripe"
    }
    fn label(&self) -> &'static str {
        "Card, Apple Pay, Google Pay (Stripe)"
    }
    async fn start(&self, order: &OrderFacts) -> Result<Started> {
        let mut form: Vec<(String, String)> = vec![
            (
                "mode".into(),
                if order.recurring.is_some() {
                    "subscription".into()
                } else {
                    "payment".into()
                },
            ),
            (
                "success_url".into(),
                format!(
                    "{}{}session_id={{CHECKOUT_SESSION_ID}}",
                    order.success_url,
                    if order.success_url.contains('?') {
                        "&"
                    } else {
                        "?"
                    }
                ),
            ),
            ("cancel_url".into(), order.cancel_url.clone()),
            ("customer_email".into(), order.customer_email.clone()),
            ("client_reference_id".into(), order.uuid.clone()),
            ("metadata[order_uuid]".into(), order.uuid.clone()),
            ("metadata[order_number]".into(), order.number.clone()),
        ];
        if let Some((interval, title)) = &order.recurring {
            form.push(("line_items[0][quantity]".into(), "1".into()));
            form.push((
                "line_items[0][price_data][currency]".into(),
                order.currency.to_lowercase(),
            ));
            form.push((
                "line_items[0][price_data][unit_amount]".into(),
                order.total_cents.to_string(),
            ));
            form.push((
                "line_items[0][price_data][recurring][interval]".into(),
                interval.clone(),
            ));
            form.push((
                "line_items[0][price_data][product_data][name]".into(),
                title.clone(),
            ));
            form.push((
                "subscription_data[metadata][order_uuid]".into(),
                order.uuid.clone(),
            ));
        } else {
            for (i, (title, unit, qty)) in order.lines.iter().enumerate() {
                form.push((format!("line_items[{i}][quantity]"), qty.to_string()));
                form.push((
                    format!("line_items[{i}][price_data][currency]"),
                    order.currency.to_lowercase(),
                ));
                form.push((
                    format!("line_items[{i}][price_data][unit_amount]"),
                    unit.to_string(),
                ));
                form.push((
                    format!("line_items[{i}][price_data][product_data][name]"),
                    title.clone(),
                ));
            }
        }
        let v = self.post("checkout/sessions", &form).await?;
        Ok(Started {
            redirect_url: v["url"].as_str().context("no checkout url")?.to_string(),
            external_id: v["id"].as_str().context("no session id")?.to_string(),
        })
    }
    async fn confirm(
        &self,
        _order: &OrderFacts,
        external_id: &str,
        _params: &[(String, String)],
    ) -> Result<Outcome> {
        let v = self
            .get(&format!("checkout/sessions/{external_id}"))
            .await?;
        Ok(match v["payment_status"].as_str() {
            Some("paid") | Some("no_payment_required") => Outcome::Paid {
                external_id: external_id.to_string(),
                subscription_id: v["subscription"].as_str().map(String::from),
                period_end: None,
            },
            Some("unpaid") => Outcome::Pending,
            other => Outcome::Failed(format!("payment status {}", other.unwrap_or("unknown"))),
        })
    }
    async fn webhook(&self, headers: &[(String, String)], body: &[u8]) -> Result<(String, Event)> {
        let sig = headers
            .iter()
            .find(|(k, _)| k.eq_ignore_ascii_case("stripe-signature"))
            .map(|(_, v)| v.as_str())
            .context("missing Stripe-Signature")?;
        Self::verify_signature(
            &self.webhook_secret,
            sig,
            body,
            chrono::Utc::now().timestamp(),
            300,
        )?;
        let v: serde_json::Value = serde_json::from_slice(body).context("webhook body")?;
        let id = v["id"].as_str().unwrap_or_default().to_string();
        let obj = &v["data"]["object"];
        let ev = match v["type"].as_str().unwrap_or("") {
            "checkout.session.completed" | "checkout.session.async_payment_succeeded" => {
                Event::Paid {
                    order_uuid: obj["metadata"]["order_uuid"]
                        .as_str()
                        .or(obj["client_reference_id"].as_str())
                        .map(String::from),
                    external_id: obj["id"].as_str().unwrap_or_default().to_string(),
                    subscription_id: obj["subscription"].as_str().map(String::from),
                    period_end: None,
                }
            }
            "charge.refunded" => Event::Refunded {
                external_id: obj["payment_intent"]
                    .as_str()
                    .or(obj["id"].as_str())
                    .unwrap_or_default()
                    .to_string(),
            },
            "invoice.paid" => Event::SubscriptionRenewed {
                subscription_id: obj["subscription"].as_str().unwrap_or_default().to_string(),
                period_end: obj["lines"]["data"][0]["period"]["end"]
                    .as_i64()
                    .map(unix_to_iso)
                    .unwrap_or_default(),
            },
            "customer.subscription.deleted" => Event::SubscriptionEnded {
                subscription_id: obj["id"].as_str().unwrap_or_default().to_string(),
            },
            other => Event::Ignored(other.to_string()),
        };
        Ok((id, ev))
    }
    async fn refund(
        &self,
        external_id: &str,
        amount_cents: i64,
        _currency: &str,
    ) -> Result<String> {
        // external_id is a Checkout Session; refunds go against its payment intent.
        let session = self
            .get(&format!("checkout/sessions/{external_id}"))
            .await?;
        let intent = session["payment_intent"]
            .as_str()
            .context("session has no payment intent")?;
        let v = self
            .post(
                "refunds",
                &[
                    ("payment_intent".to_string(), intent.to_string()),
                    ("amount".to_string(), amount_cents.to_string()),
                ],
            )
            .await?;
        Ok(v["id"].as_str().unwrap_or_default().to_string())
    }
    async fn cancel_subscription(&self, subscription_id: &str, at_period_end: bool) -> Result<()> {
        if at_period_end {
            self.post(
                &format!("subscriptions/{subscription_id}"),
                &[("cancel_at_period_end".to_string(), "true".to_string())],
            )
            .await?;
        } else {
            let res = self
                .http
                .delete(format!(
                    "https://api.stripe.com/v1/subscriptions/{subscription_id}"
                ))
                .basic_auth(&self.secret_key, None::<&str>)
                .send()
                .await?;
            if !res.status().is_success() {
                bail!("Stripe refused to cancel the subscription");
            }
        }
        Ok(())
    }
}

// ----- PayPal: Orders API v2 with capture on return, verified webhooks -----

pub struct PayPal {
    pub client_id: String,
    pub secret: String,
    pub webhook_id: String,
    pub sandbox: bool,
    pub http: reqwest::Client,
}

impl PayPal {
    pub fn new(client_id: &str, secret: &str, webhook_id: &str, sandbox: bool) -> Self {
        Self {
            client_id: client_id.into(),
            secret: secret.into(),
            webhook_id: webhook_id.into(),
            sandbox,
            http: reqwest::Client::new(),
        }
    }
    fn api(&self) -> &'static str {
        if self.sandbox {
            "https://api-m.sandbox.paypal.com"
        } else {
            "https://api-m.paypal.com"
        }
    }
    async fn token(&self) -> Result<String> {
        let v: serde_json::Value = self
            .http
            .post(format!("{}/v1/oauth2/token", self.api()))
            .basic_auth(&self.client_id, Some(&self.secret))
            .form(&[("grant_type", "client_credentials")])
            .send()
            .await
            .context("PayPal token request failed")?
            .json()
            .await?;
        v["access_token"]
            .as_str()
            .map(String::from)
            .context("PayPal did not issue a token")
    }
    async fn call(
        &self,
        method: reqwest::Method,
        path: &str,
        body: Option<serde_json::Value>,
    ) -> Result<serde_json::Value> {
        let token = self.token().await?;
        let mut req = self
            .http
            .request(method, format!("{}{path}", self.api()))
            .bearer_auth(token)
            .header("Content-Type", "application/json");
        if let Some(b) = body {
            req = req.json(&b);
        }
        let res = req.send().await.context("PayPal request failed")?;
        let status = res.status();
        let text = res.text().await?;
        let v: serde_json::Value = if text.is_empty() {
            serde_json::json!({})
        } else {
            serde_json::from_str(&text).unwrap_or(serde_json::json!({ "raw": text }))
        };
        if !status.is_success() {
            bail!(
                "PayPal: {}",
                v["message"]
                    .as_str()
                    .or(v["error_description"].as_str())
                    .unwrap_or("request refused")
            );
        }
        Ok(v)
    }
}

#[async_trait]
impl Gateway for PayPal {
    fn name(&self) -> &'static str {
        "paypal"
    }
    fn label(&self) -> &'static str {
        "PayPal"
    }
    async fn start(&self, order: &OrderFacts) -> Result<Started> {
        if order.recurring.is_some() {
            bail!("Recurring passes are sold through Stripe; PayPal subscriptions arrive in a later release");
        }
        let amount = format!("{}.{:02}", order.total_cents / 100, order.total_cents % 100);
        let body = serde_json::json!({
            "intent": "CAPTURE",
            "purchase_units": [{ "reference_id": order.uuid, "custom_id": order.uuid, "invoice_id": order.number, "amount": { "currency_code": order.currency, "value": amount } }],
            "payment_source": { "paypal": { "experience_context": { "return_url": order.success_url, "cancel_url": order.cancel_url, "user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING" } } }
        });
        let v = self
            .call(reqwest::Method::POST, "/v2/checkout/orders", Some(body))
            .await?;
        let approve = v["links"]
            .as_array()
            .and_then(|l| {
                l.iter()
                    .find(|x| x["rel"] == "payer-action" || x["rel"] == "approve")
            })
            .and_then(|x| x["href"].as_str())
            .context("PayPal gave no approval link")?;
        Ok(Started {
            redirect_url: approve.to_string(),
            external_id: v["id"].as_str().context("no PayPal order id")?.to_string(),
        })
    }
    async fn confirm(
        &self,
        _order: &OrderFacts,
        external_id: &str,
        _params: &[(String, String)],
    ) -> Result<Outcome> {
        let v = self
            .call(
                reqwest::Method::POST,
                &format!("/v2/checkout/orders/{external_id}/capture"),
                Some(serde_json::json!({})),
            )
            .await?;
        Ok(match v["status"].as_str() {
            Some("COMPLETED") => Outcome::Paid {
                external_id: external_id.to_string(),
                subscription_id: None,
                period_end: None,
            },
            Some("APPROVED") | Some("PAYER_ACTION_REQUIRED") => Outcome::Pending,
            other => Outcome::Failed(format!("PayPal status {}", other.unwrap_or("unknown"))),
        })
    }
    async fn webhook(&self, headers: &[(String, String)], body: &[u8]) -> Result<(String, Event)> {
        let h = |name: &str| {
            headers
                .iter()
                .find(|(k, _)| k.eq_ignore_ascii_case(name))
                .map(|(_, v)| v.clone())
                .unwrap_or_default()
        };
        let event: serde_json::Value = serde_json::from_slice(body).context("webhook body")?;
        let verify = serde_json::json!({
            "auth_algo": h("paypal-auth-algo"), "cert_url": h("paypal-cert-url"), "transmission_id": h("paypal-transmission-id"),
            "transmission_sig": h("paypal-transmission-sig"), "transmission_time": h("paypal-transmission-time"), "webhook_id": self.webhook_id, "webhook_event": event
        });
        let v = self
            .call(
                reqwest::Method::POST,
                "/v1/notifications/verify-webhook-signature",
                Some(verify),
            )
            .await?;
        if v["verification_status"] != "SUCCESS" {
            bail!("PayPal webhook signature not verified");
        }
        let id = event["id"].as_str().unwrap_or_default().to_string();
        let res = &event["resource"];
        let ev = match event["event_type"].as_str().unwrap_or("") {
            "CHECKOUT.ORDER.APPROVED" | "PAYMENT.CAPTURE.COMPLETED" => Event::Paid {
                order_uuid: res["custom_id"]
                    .as_str()
                    .or(res["purchase_units"][0]["custom_id"].as_str())
                    .map(String::from),
                external_id: res["supplementary_data"]["related_ids"]["order_id"]
                    .as_str()
                    .or(res["id"].as_str())
                    .unwrap_or_default()
                    .to_string(),
                subscription_id: None,
                period_end: None,
            },
            "PAYMENT.CAPTURE.REFUNDED" => Event::Refunded {
                external_id: res["supplementary_data"]["related_ids"]["order_id"]
                    .as_str()
                    .unwrap_or_default()
                    .to_string(),
            },
            other => Event::Ignored(other.to_string()),
        };
        Ok((id, ev))
    }
    async fn refund(&self, external_id: &str, amount_cents: i64, currency: &str) -> Result<String> {
        let order = self
            .call(
                reqwest::Method::GET,
                &format!("/v2/checkout/orders/{external_id}"),
                None,
            )
            .await?;
        let capture = order["purchase_units"][0]["payments"]["captures"][0]["id"]
            .as_str()
            .context("order has no capture to refund")?;
        let body = serde_json::json!({ "amount": { "value": format!("{}.{:02}", amount_cents / 100, amount_cents % 100), "currency_code": currency } });
        let v = self
            .call(
                reqwest::Method::POST,
                &format!("/v2/payments/captures/{capture}/refund"),
                Some(body),
            )
            .await?;
        Ok(v["id"].as_str().unwrap_or_default().to_string())
    }
    async fn cancel_subscription(
        &self,
        _subscription_id: &str,
        _at_period_end: bool,
    ) -> Result<()> {
        bail!("PayPal subscriptions are not available in this release")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stripe_signature_round_trip() {
        let secret = "whsec_test";
        let body = br#"{"id":"evt_1","type":"checkout.session.completed"}"#;
        let ts = 1_700_000_000;
        let mut mac = Hmac::<Sha256>::new_from_slice(secret.as_bytes()).unwrap();
        mac.update(format!("{ts}.").as_bytes());
        mac.update(body);
        let sig = hex(&mac.finalize().into_bytes());
        let header = format!("t={ts},v1={sig},v0=deadbeef");
        assert!(Stripe::verify_signature(secret, &header, body, ts + 10, 300).is_ok());
        assert!(
            Stripe::verify_signature(secret, &header, body, ts + 1000, 300).is_err(),
            "stale"
        );
        assert!(
            Stripe::verify_signature("other", &header, body, ts, 300).is_err(),
            "wrong secret"
        );
        assert!(Stripe::verify_signature(secret, &header, b"tampered", ts, 300).is_err());
    }

    #[tokio::test]
    async fn test_gateway_flow() {
        let g = TestGateway {
            base_url: "http://x/mms".into(),
        };
        let facts = OrderFacts {
            uuid: "o1".into(),
            number: "ORD-1".into(),
            currency: "USD".into(),
            total_cents: 100,
            customer_email: "a@b.c".into(),
            lines: vec![],
            recurring: Some(("month".into(), "Pass".into())),
            success_url: String::new(),
            cancel_url: String::new(),
        };
        let s = g.start(&facts).await.unwrap();
        assert_eq!(s.redirect_url, "http://x/mms/checkout/test/o1");
        match g.confirm(&facts, &s.external_id, &[]).await.unwrap() {
            Outcome::Paid {
                subscription_id,
                period_end,
                ..
            } => {
                assert_eq!(subscription_id.as_deref(), Some("sub_test_o1"));
                assert!(period_end.is_some());
            }
            other => panic!("{other:?}"),
        }
        assert_eq!(
            g.confirm(&facts, "x", &[("result".into(), "fail".into())])
                .await
                .unwrap(),
            Outcome::Failed("Declined by the test gateway".into())
        );
        let (id, ev) = g
            .webhook(
                &[],
                br#"{"id":"e1","kind":"refunded","external_id":"test_o1"}"#,
            )
            .await
            .unwrap();
        assert_eq!(
            (id.as_str(), ev),
            (
                "e1",
                Event::Refunded {
                    external_id: "test_o1".into()
                }
            )
        );
    }
}
