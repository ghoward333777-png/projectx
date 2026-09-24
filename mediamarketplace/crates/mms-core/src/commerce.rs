//! Cart, coupons, tax, orders, receipts and subscriptions. The server owns all of
//! it; gateways only move money (see `gateways`).

use crate::db::Db;
use crate::entitlements::{Entitlements, Grant};
use crate::products::{Product, Products};
use anyhow::{bail, Result};
use serde::Serialize;

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Cart {
    pub id: i64,
    pub token: String,
    pub user_id: Option<i64>,
    pub coupon: Option<String>,
    pub country: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct CartLine {
    pub product: Product,
    pub quantity: i64,
    pub unit_cents: i64,
    pub total_cents: i64,
    pub max_quantity: i64,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Coupon {
    pub id: i64,
    pub code: String,
    pub kind: String,
    pub amount: i64,
    pub currency: String,
    pub max_uses: i64,
    pub uses: i64,
    pub expires_at: Option<String>,
    pub status: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct TaxRate {
    pub id: i64,
    pub country: String,
    pub region: String,
    pub name: String,
    pub rate_bp: i64,
}

/// Money maths shared by the cart page, checkout and the order record.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct Totals {
    pub subtotal_cents: i64,
    pub discount_cents: i64,
    pub tax_cents: i64,
    pub total_cents: i64,
    pub tax_name: String,
    pub tax_rate_bp: i64,
    pub coupon: Option<String>,
}

/// Pure and deterministic: discount then tax on the discounted amount, rounded
/// half up to the cent.
pub fn totals(subtotal_cents: i64, coupon: Option<&Coupon>, tax: Option<&TaxRate>) -> Totals {
    let discount = match coupon {
        Some(c) if c.kind == "percent" => (subtotal_cents * c.amount.clamp(0, 100) + 50) / 100,
        Some(c) => c.amount.min(subtotal_cents).max(0),
        None => 0,
    };
    let taxable = subtotal_cents - discount;
    let (tax_cents, tax_name, rate) = match tax {
        Some(t) => (
            (taxable * t.rate_bp + 5000) / 10000,
            t.name.clone(),
            t.rate_bp,
        ),
        None => (0, String::new(), 0),
    };
    Totals {
        subtotal_cents,
        discount_cents: discount,
        tax_cents,
        total_cents: taxable + tax_cents,
        tax_name,
        tax_rate_bp: rate,
        coupon: coupon.map(|c| c.code.clone()),
    }
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Order {
    pub id: i64,
    pub uuid: String,
    pub number: String,
    pub user_id: i64,
    pub status: String,
    pub currency: String,
    pub subtotal_cents: i64,
    pub discount_cents: i64,
    pub tax_cents: i64,
    pub total_cents: i64,
    pub coupon: Option<String>,
    pub country: String,
    pub tax_name: String,
    pub tax_rate_bp: i64,
    pub gateway: String,
    pub external_id: Option<String>,
    pub paid_at: Option<String>,
    pub created_at: String,
    pub base_currency: String,
    pub fx_rate: f64,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct OrderItem {
    pub id: i64,
    pub order_id: i64,
    pub product_id: Option<i64>,
    pub title: String,
    pub r#type: String,
    pub unit_cents: i64,
    pub quantity: i64,
    pub total_cents: i64,
    pub settings: Option<String>,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Payment {
    pub id: i64,
    pub order_id: i64,
    pub gateway: String,
    pub external_id: Option<String>,
    pub amount_cents: i64,
    pub currency: String,
    pub status: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Subscription {
    pub id: i64,
    pub uuid: String,
    pub user_id: i64,
    pub product_id: i64,
    pub order_id: Option<i64>,
    pub gateway: String,
    pub external_id: Option<String>,
    pub interval: String,
    pub status: String,
    pub period_end: Option<String>,
    pub cancel_at_period_end: i64,
    pub created_at: String,
}

const ORDER_SELECT: &str = "SELECT id, uuid, number, user_id, status, currency, subtotal_cents, discount_cents, tax_cents, total_cents, coupon, country, tax_name, tax_rate_bp, gateway, external_id, paid_at, created_at, base_currency, fx_rate FROM orders";
const SUB_SELECT: &str = "SELECT id, uuid, user_id, product_id, order_id, gateway, external_id, interval, status, period_end, cancel_at_period_end, created_at FROM subscriptions";

/// Seats for meetings, one copy of everything else.
pub fn max_quantity(p: &Product) -> i64 {
    match p.r#type.as_str() {
        "meeting" | "consultation" => p.setting("capacity").parse().unwrap_or(1).max(1),
        _ => 1,
    }
}

/// Whether a product is a recurring subscription (site pass with recurring validity).
pub fn is_recurring(p: &Product) -> bool {
    p.r#type == "site_pass" && p.setting("validity") == "recurring"
}

pub fn recurring_interval(p: &Product) -> String {
    match p.setting("interval").as_str() {
        "year" => "year".into(),
        _ => "month".into(),
    }
}

#[derive(Clone)]
pub struct Commerce {
    db: Db,
    products: Products,
    entitlements: Entitlements,
}

impl Commerce {
    pub fn new(db: Db) -> Self {
        Self {
            products: Products::new(db.clone()),
            entitlements: Entitlements::new(db.clone()),
            db,
        }
    }

    // ----- carts -----

    /// Finds the cart for a cookie token, adopting it for the signed-in user and
    /// merging any older cart that user left on another device.
    pub async fn cart(&self, token: &str, user_id: Option<i64>) -> Result<Cart> {
        let now = crate::now();
        let mut cart = match sqlx::query_as::<_, Cart>(
            "SELECT id, token, user_id, coupon, country FROM carts WHERE token = ?",
        )
        .bind(token)
        .fetch_optional(&self.db.pool)
        .await?
        {
            Some(c) => c,
            None => {
                sqlx::query("INSERT INTO carts (token, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)")
                    .bind(token).bind(user_id).bind(&now).bind(&now).execute(&self.db.pool).await?;
                sqlx::query_as::<_, Cart>(
                    "SELECT id, token, user_id, coupon, country FROM carts WHERE token = ?",
                )
                .bind(token)
                .fetch_one(&self.db.pool)
                .await?
            }
        };
        if let Some(uid) = user_id {
            if cart.user_id != Some(uid) {
                // Merge the user's previous cart(s) into this one, then adopt it.
                let others: Vec<i64> =
                    sqlx::query_scalar("SELECT id FROM carts WHERE user_id = ? AND id != ?")
                        .bind(uid)
                        .bind(cart.id)
                        .fetch_all(&self.db.pool)
                        .await?;
                for other in others {
                    sqlx::query("INSERT OR IGNORE INTO cart_items (cart_id, product_id, quantity, added_at) SELECT ?, product_id, quantity, added_at FROM cart_items WHERE cart_id = ?")
                        .bind(cart.id).bind(other).execute(&self.db.pool).await?;
                    sqlx::query("DELETE FROM carts WHERE id = ?")
                        .bind(other)
                        .execute(&self.db.pool)
                        .await?;
                }
                sqlx::query("UPDATE carts SET user_id = ?, updated_at = ? WHERE id = ?")
                    .bind(uid)
                    .bind(&now)
                    .bind(cart.id)
                    .execute(&self.db.pool)
                    .await?;
                cart.user_id = Some(uid);
            }
        }
        Ok(cart)
    }

    pub async fn add(&self, cart: &Cart, product: &Product, quantity: i64) -> Result<()> {
        if product.status != "published" {
            bail!("This product is not available");
        }
        let q = quantity.clamp(1, max_quantity(product));
        sqlx::query("INSERT INTO cart_items (cart_id, product_id, quantity, added_at) VALUES (?, ?, ?, ?) ON CONFLICT(cart_id, product_id) DO UPDATE SET quantity = MIN(excluded.quantity + cart_items.quantity, ?)")
            .bind(cart.id).bind(product.id).bind(q).bind(crate::now()).bind(max_quantity(product))
            .execute(&self.db.pool).await?;
        Ok(())
    }

    pub async fn set_quantity(&self, cart: &Cart, product_id: i64, quantity: i64) -> Result<()> {
        if quantity <= 0 {
            return self.remove(cart, product_id).await;
        }
        let Some(p) = self.products.by_id(product_id).await? else {
            return Ok(());
        };
        sqlx::query("UPDATE cart_items SET quantity = ? WHERE cart_id = ? AND product_id = ?")
            .bind(quantity.min(max_quantity(&p)))
            .bind(cart.id)
            .bind(product_id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    pub async fn remove(&self, cart: &Cart, product_id: i64) -> Result<()> {
        sqlx::query("DELETE FROM cart_items WHERE cart_id = ? AND product_id = ?")
            .bind(cart.id)
            .bind(product_id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    pub async fn clear(&self, cart: &Cart) -> Result<()> {
        sqlx::query("DELETE FROM cart_items WHERE cart_id = ?")
            .bind(cart.id)
            .execute(&self.db.pool)
            .await?;
        sqlx::query("UPDATE carts SET coupon = NULL WHERE id = ?")
            .bind(cart.id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    pub async fn set_country(&self, cart: &Cart, country: &str) -> Result<()> {
        let c: String = country
            .trim()
            .to_ascii_uppercase()
            .chars()
            .filter(|c| c.is_ascii_alphabetic())
            .take(2)
            .collect();
        sqlx::query("UPDATE carts SET country = ? WHERE id = ?")
            .bind(c)
            .bind(cart.id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    pub async fn set_coupon(&self, cart: &Cart, code: &str) -> Result<Option<Coupon>> {
        let code = code.trim().to_ascii_uppercase();
        if code.is_empty() {
            sqlx::query("UPDATE carts SET coupon = NULL WHERE id = ?")
                .bind(cart.id)
                .execute(&self.db.pool)
                .await?;
            return Ok(None);
        }
        let Some(c) = self.valid_coupon(&code).await? else {
            bail!("That coupon is not valid");
        };
        sqlx::query("UPDATE carts SET coupon = ? WHERE id = ?")
            .bind(&c.code)
            .bind(cart.id)
            .execute(&self.db.pool)
            .await?;
        Ok(Some(c))
    }

    pub async fn lines(&self, cart: &Cart) -> Result<Vec<CartLine>> {
        let rows: Vec<(i64, i64)> = sqlx::query_as(
            "SELECT product_id, quantity FROM cart_items WHERE cart_id = ? ORDER BY id",
        )
        .bind(cart.id)
        .fetch_all(&self.db.pool)
        .await?;
        let mut out = Vec::new();
        for (pid, q) in rows {
            if let Some(p) = self.products.by_id(pid).await? {
                if p.status != "published" {
                    continue;
                }
                let max = max_quantity(&p);
                let q = q.min(max);
                out.push(CartLine {
                    unit_cents: p.price_cents,
                    total_cents: p.price_cents * q,
                    quantity: q,
                    max_quantity: max,
                    product: p,
                });
            }
        }
        Ok(out)
    }

    pub async fn cart_totals(&self, cart: &Cart, lines: &[CartLine]) -> Result<Totals> {
        let subtotal: i64 = lines.iter().map(|l| l.total_cents).sum();
        let coupon = match &cart.coupon {
            Some(c) => self.valid_coupon(c).await?,
            None => None,
        };
        let tax = self.tax_for(&cart.country).await?;
        Ok(totals(subtotal, coupon.as_ref(), tax.as_ref()))
    }

    // ----- coupons and tax -----

    pub async fn valid_coupon(&self, code: &str) -> Result<Option<Coupon>> {
        let c = sqlx::query_as::<_, Coupon>("SELECT id, code, kind, amount, currency, max_uses, uses, expires_at, status, created_at FROM coupons WHERE code = ? AND status = 'active'")
            .bind(code.trim().to_ascii_uppercase()).fetch_optional(&self.db.pool).await?;
        Ok(c.filter(|c| {
            (c.max_uses == 0 || c.uses < c.max_uses)
                && c.expires_at
                    .as_deref()
                    .map(|e| e > crate::now().as_str())
                    .unwrap_or(true)
        }))
    }

    pub async fn coupons(&self) -> Result<Vec<Coupon>> {
        Ok(sqlx::query_as::<_, Coupon>("SELECT id, code, kind, amount, currency, max_uses, uses, expires_at, status, created_at FROM coupons ORDER BY id DESC").fetch_all(&self.db.pool).await?)
    }

    pub async fn create_coupon(
        &self,
        code: &str,
        kind: &str,
        amount: i64,
        max_uses: i64,
        expires_at: Option<&str>,
    ) -> Result<()> {
        let code: String = code
            .trim()
            .to_ascii_uppercase()
            .chars()
            .filter(|c| c.is_ascii_alphanumeric() || *c == '-')
            .collect();
        if code.len() < 3 {
            bail!("Coupon codes need at least three letters or digits");
        }
        if !matches!(kind, "percent" | "fixed")
            || amount <= 0
            || (kind == "percent" && amount > 100)
        {
            bail!("Enter a percentage between 1 and 100 or a fixed amount in cents");
        }
        sqlx::query("INSERT INTO coupons (code, kind, amount, max_uses, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)")
            .bind(&code).bind(kind).bind(amount).bind(max_uses.max(0)).bind(expires_at.filter(|e| !e.is_empty())).bind(crate::now())
            .execute(&self.db.pool).await.map_err(|_| anyhow::anyhow!("A coupon with that code already exists"))?;
        Ok(())
    }

    pub async fn set_coupon_status(&self, id: i64, status: &str) -> Result<()> {
        sqlx::query("UPDATE coupons SET status = ? WHERE id = ?")
            .bind(if status == "active" {
                "active"
            } else {
                "disabled"
            })
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    pub async fn tax_for(&self, country: &str) -> Result<Option<TaxRate>> {
        if country.is_empty() {
            return Ok(None);
        }
        Ok(sqlx::query_as::<_, TaxRate>("SELECT id, country, region, name, rate_bp FROM tax_rates WHERE country = ? AND region = '' LIMIT 1")
            .bind(country).fetch_optional(&self.db.pool).await?)
    }

    pub async fn tax_rates(&self) -> Result<Vec<TaxRate>> {
        Ok(sqlx::query_as::<_, TaxRate>(
            "SELECT id, country, region, name, rate_bp FROM tax_rates ORDER BY country, region",
        )
        .fetch_all(&self.db.pool)
        .await?)
    }

    pub async fn set_tax_rate(&self, country: &str, name: &str, rate_bp: i64) -> Result<()> {
        let country: String = country
            .trim()
            .to_ascii_uppercase()
            .chars()
            .filter(|c| c.is_ascii_alphabetic())
            .take(2)
            .collect();
        if country.len() != 2 || !(0..=10000).contains(&rate_bp) {
            bail!("Use a two-letter country code and a rate between 0 and 100%");
        }
        sqlx::query("INSERT INTO tax_rates (country, region, name, rate_bp, created_at) VALUES (?, '', ?, ?, ?) ON CONFLICT(country, region) DO UPDATE SET name = excluded.name, rate_bp = excluded.rate_bp")
            .bind(&country).bind(name.trim()).bind(rate_bp).bind(crate::now()).execute(&self.db.pool).await?;
        Ok(())
    }

    pub async fn delete_tax_rate(&self, id: i64) -> Result<()> {
        sqlx::query("DELETE FROM tax_rates WHERE id = ?")
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    // ----- orders -----

    /// Turns the cart into a pending order (items are copied so later price changes
    /// never alter history). The cart is emptied once the order is paid.
    pub async fn create_order(&self, cart: &Cart, user_id: i64, currency: &str) -> Result<Order> {
        self.create_order_in(cart, user_id, currency, None).await
    }

    /// Like `create_order`, optionally charging in another currency at `factor`
    /// (charge = base × factor); the base currency and rate are kept on the order.
    pub async fn create_order_in(
        &self,
        cart: &Cart,
        user_id: i64,
        base_currency: &str,
        charge: Option<(&str, f64)>,
    ) -> Result<Order> {
        let lines = self.lines(cart).await?;
        if lines.is_empty() {
            bail!("Your cart is empty");
        }
        let mut t = self.cart_totals(cart, &lines).await?;
        let (currency, fx) = match charge {
            Some((code, factor)) if factor > 0.0 && code != base_currency => {
                let conv = |c: i64| ((c as f64) * factor).round() as i64;
                t.subtotal_cents = conv(t.subtotal_cents);
                t.discount_cents = conv(t.discount_cents);
                t.tax_cents = conv(t.tax_cents);
                t.total_cents = t.subtotal_cents - t.discount_cents + t.tax_cents;
                (code.to_string(), factor)
            }
            _ => (base_currency.to_string(), 1.0),
        };
        let currency = currency.as_str();
        let now = crate::now();
        let year = now[..4].to_string();
        let seq: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM orders WHERE number LIKE ?")
            .bind(format!("ORD-{year}-%"))
            .fetch_one(&self.db.pool)
            .await?;
        let number = format!("ORD-{year}-{:05}", seq + 1);
        let uuid = uuid::Uuid::new_v4().to_string();
        let id = sqlx::query("INSERT INTO orders (uuid, number, user_id, status, currency, subtotal_cents, discount_cents, tax_cents, total_cents, coupon, country, tax_name, tax_rate_bp, base_currency, fx_rate, created_at, updated_at) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
            .bind(&uuid).bind(&number).bind(user_id).bind(currency).bind(t.subtotal_cents).bind(t.discount_cents).bind(t.tax_cents).bind(t.total_cents)
            .bind(&t.coupon).bind(&cart.country).bind(&t.tax_name).bind(t.tax_rate_bp).bind(base_currency).bind(fx).bind(&now).bind(&now)
            .execute(&self.db.pool).await?.last_insert_rowid();
        let conv = |c: i64| ((c as f64) * fx).round() as i64;
        for l in &lines {
            sqlx::query("INSERT INTO order_items (order_id, product_id, title, type, unit_cents, quantity, total_cents, settings) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
                .bind(id).bind(l.product.id).bind(&l.product.title).bind(&l.product.r#type).bind(conv(l.unit_cents)).bind(l.quantity).bind(conv(l.total_cents)).bind(&l.product.settings)
                .execute(&self.db.pool).await?;
        }
        Ok(self.order_by_id(id).await?.expect("order just created"))
    }

    /// An order reported by the CMS shop (WooCommerce, VirtueMart): the money was taken
    /// there, so the order is created pending with the shop's own amounts and then
    /// completed through `mark_paid` like every other order. `items` are
    /// (product, quantity, unit price in cents). Amounts are whatever the shop charged,
    /// including its own discounts and tax, so reports agree with the shop.
    #[allow(clippy::too_many_arguments)]
    pub async fn create_external_order(
        &self,
        user_id: i64,
        gateway: &str,
        external_id: &str,
        currency: &str,
        items: &[(Product, i64, i64)],
        discount_cents: i64,
        tax_cents: i64,
        country: &str,
    ) -> Result<Order> {
        if items.is_empty() {
            bail!("The order has no store products");
        }
        let now = crate::now();
        let year = now[..4].to_string();
        let seq: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM orders WHERE number LIKE ?")
            .bind(format!("ORD-{year}-%"))
            .fetch_one(&self.db.pool)
            .await?;
        let number = format!("ORD-{year}-{:05}", seq + 1);
        let uuid = uuid::Uuid::new_v4().to_string();
        let subtotal: i64 = items.iter().map(|(_, q, u)| q * u).sum();
        let total = (subtotal - discount_cents + tax_cents).max(0);
        let id = sqlx::query("INSERT INTO orders (uuid, number, user_id, status, currency, subtotal_cents, discount_cents, tax_cents, total_cents, coupon, country, tax_name, tax_rate_bp, gateway, external_id, base_currency, fx_rate, created_at, updated_at) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, NULL, ?, '', 0, ?, ?, ?, 1.0, ?, ?)")
            .bind(&uuid).bind(&number).bind(user_id).bind(currency).bind(subtotal).bind(discount_cents.max(0)).bind(tax_cents.max(0)).bind(total)
            .bind(country).bind(gateway).bind(external_id).bind(currency).bind(&now).bind(&now)
            .execute(&self.db.pool).await?.last_insert_rowid();
        for (p, quantity, unit) in items {
            let quantity = (*quantity).clamp(1, max_quantity(p));
            sqlx::query("INSERT INTO order_items (order_id, product_id, title, type, unit_cents, quantity, total_cents, settings) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
                .bind(id).bind(p.id).bind(&p.title).bind(&p.r#type).bind(unit).bind(quantity).bind(unit * quantity).bind(&p.settings)
                .execute(&self.db.pool).await?;
        }
        Ok(self.order_by_id(id).await?.expect("order just created"))
    }

    pub async fn set_gateway(
        &self,
        order_id: i64,
        gateway: &str,
        external_id: Option<&str>,
    ) -> Result<()> {
        sqlx::query("UPDATE orders SET gateway = ?, external_id = ?, updated_at = ? WHERE id = ?")
            .bind(gateway)
            .bind(external_id)
            .bind(crate::now())
            .bind(order_id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn record_payment(
        &self,
        order_id: i64,
        gateway: &str,
        external_id: Option<&str>,
        amount_cents: i64,
        currency: &str,
        status: &str,
        raw: Option<&str>,
    ) -> Result<i64> {
        let now = crate::now();
        let id = sqlx::query("INSERT INTO payments (order_id, gateway, external_id, amount_cents, currency, status, raw, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
            .bind(order_id).bind(gateway).bind(external_id).bind(amount_cents).bind(currency).bind(status).bind(raw).bind(&now).bind(&now)
            .execute(&self.db.pool).await?.last_insert_rowid();
        Ok(id)
    }

    /// Marks an order paid exactly once and grants everything in it. Safe to call
    /// again from a webhook after the return URL already did the work.
    pub async fn mark_paid(
        &self,
        order: &Order,
        gateway: &str,
        external_id: Option<&str>,
        receipt_prefix: &str,
        site_name: &str,
        footer: &str,
    ) -> Result<bool> {
        if order.status == "paid" {
            return Ok(false);
        }
        let now = crate::now();
        let r = sqlx::query("UPDATE orders SET status = 'paid', gateway = ?, external_id = COALESCE(?, external_id), paid_at = ?, updated_at = ? WHERE id = ? AND status = 'pending'")
            .bind(gateway).bind(external_id).bind(&now).bind(&now).bind(order.id)
            .execute(&self.db.pool).await?;
        if r.rows_affected() == 0 {
            return Ok(false);
        }
        if order.total_cents > 0 {
            self.record_payment(
                order.id,
                gateway,
                external_id,
                order.total_cents,
                &order.currency,
                "succeeded",
                None,
            )
            .await?;
        }
        if let Some(code) = &order.coupon {
            sqlx::query("UPDATE coupons SET uses = uses + 1 WHERE code = ?")
                .bind(code)
                .execute(&self.db.pool)
                .await?;
        }
        for item in self.items(order.id).await? {
            let Some(pid) = item.product_id else { continue };
            let Some(p) = self.products.by_id(pid).await? else {
                continue;
            };
            self.grant_for_product(order.user_id, &p, "order", &order.uuid, &now)
                .await?;
            sqlx::query("UPDATE products SET purchases = purchases + ? WHERE id = ?")
                .bind(item.quantity)
                .bind(pid)
                .execute(&self.db.pool)
                .await?;
        }
        if let Some(cart_id) = sqlx::query_scalar::<_, Option<i64>>(
            "SELECT id FROM carts WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        )
        .bind(order.user_id)
        .fetch_optional(&self.db.pool)
        .await?
        .flatten()
        {
            sqlx::query("DELETE FROM cart_items WHERE cart_id = ?")
                .bind(cart_id)
                .execute(&self.db.pool)
                .await?;
            sqlx::query("UPDATE carts SET coupon = NULL WHERE id = ?")
                .bind(cart_id)
                .execute(&self.db.pool)
                .await?;
        }
        self.issue_receipt(order.id, receipt_prefix, site_name, footer)
            .await?;
        Ok(true)
    }

    /// The entitlement a paid product produces. Site passes cover the site (or
    /// their categories) for their validity; pages unlock the page; everything else
    /// unlocks the product itself.
    pub async fn grant_for_product(
        &self,
        user_id: i64,
        p: &Product,
        source: &str,
        source_ref: &str,
        now: &str,
    ) -> Result<()> {
        let (scope, scope_ref, ends_at): (&str, String, Option<String>) = match p.r#type.as_str() {
            "site_pass" => {
                let ends = match p.setting("validity").as_str() {
                    "days" => Some(add_days(now, p.setting("days").parse().unwrap_or(30))),
                    "date" => {
                        let d = p.setting("until");
                        if d.len() >= 10 {
                            Some(format!("{}T23:59:59Z", &d[..10]))
                        } else {
                            None
                        }
                    }
                    "recurring" => Some(add_days(
                        now,
                        if recurring_interval(p) == "year" {
                            366
                        } else {
                            31
                        },
                    )),
                    _ => None,
                };
                if p.setting("scope") == "categories" {
                    let cats = self.products.category_ids(p.id).await?;
                    for c in cats {
                        let slug: Option<String> =
                            sqlx::query_scalar("SELECT slug FROM categories WHERE id = ?")
                                .bind(c)
                                .fetch_optional(&self.db.pool)
                                .await?;
                        if let Some(slug) = slug {
                            self.entitlements
                                .grant(Grant {
                                    user_id,
                                    product_id: Some(p.id),
                                    scope: "category",
                                    scope_ref: &slug,
                                    source,
                                    source_ref,
                                    starts_at: now,
                                    ends_at: ends.as_deref(),
                                })
                                .await?;
                        }
                    }
                    return Ok(());
                }
                ("site", String::new(), ends)
            }
            "private_page" => ("page", p.setting("page_uuid"), None),
            _ => ("product", String::new(), None),
        };
        self.entitlements
            .grant(Grant {
                user_id,
                product_id: Some(p.id),
                scope,
                scope_ref: &scope_ref,
                source,
                source_ref,
                starts_at: now,
                ends_at: ends_at.as_deref(),
            })
            .await?;
        Ok(())
    }

    pub async fn cancel(&self, order_id: i64) -> Result<()> {
        sqlx::query("UPDATE orders SET status = 'cancelled', updated_at = ? WHERE id = ? AND status = 'pending'")
            .bind(crate::now()).bind(order_id).execute(&self.db.pool).await?;
        Ok(())
    }

    /// Records a refund and revokes what the order granted.
    pub async fn mark_refunded(
        &self,
        order: &Order,
        external_id: Option<&str>,
        reason: &str,
    ) -> Result<()> {
        let now = crate::now();
        if let Some(payment) = self
            .payments(order.id)
            .await?
            .into_iter()
            .find(|p| p.status == "succeeded")
        {
            sqlx::query("INSERT INTO refunds (payment_id, amount_cents, external_id, reason, created_at) VALUES (?, ?, ?, ?, ?)")
                .bind(payment.id).bind(payment.amount_cents).bind(external_id).bind(reason).bind(&now).execute(&self.db.pool).await?;
            sqlx::query("UPDATE payments SET status = 'refunded', updated_at = ? WHERE id = ?")
                .bind(&now)
                .bind(payment.id)
                .execute(&self.db.pool)
                .await?;
        }
        sqlx::query("UPDATE orders SET status = 'refunded', updated_at = ? WHERE id = ?")
            .bind(&now)
            .bind(order.id)
            .execute(&self.db.pool)
            .await?;
        self.entitlements
            .revoke_source("order", &order.uuid)
            .await?;
        Ok(())
    }

    pub async fn order_by_id(&self, id: i64) -> Result<Option<Order>> {
        Ok(
            sqlx::query_as::<_, Order>(&format!("{ORDER_SELECT} WHERE id = ?"))
                .bind(id)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn order_by_uuid(&self, uuid: &str) -> Result<Option<Order>> {
        Ok(
            sqlx::query_as::<_, Order>(&format!("{ORDER_SELECT} WHERE uuid = ?"))
                .bind(uuid)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn order_by_external(
        &self,
        gateway: &str,
        external_id: &str,
    ) -> Result<Option<Order>> {
        Ok(sqlx::query_as::<_, Order>(&format!(
            "{ORDER_SELECT} WHERE gateway = ? AND external_id = ?"
        ))
        .bind(gateway)
        .bind(external_id)
        .fetch_optional(&self.db.pool)
        .await?)
    }

    pub async fn items(&self, order_id: i64) -> Result<Vec<OrderItem>> {
        Ok(sqlx::query_as::<_, OrderItem>("SELECT id, order_id, product_id, title, type, unit_cents, quantity, total_cents, settings FROM order_items WHERE order_id = ? ORDER BY id")
            .bind(order_id).fetch_all(&self.db.pool).await?)
    }

    pub async fn payments(&self, order_id: i64) -> Result<Vec<Payment>> {
        Ok(sqlx::query_as::<_, Payment>("SELECT id, order_id, gateway, external_id, amount_cents, currency, status, created_at FROM payments WHERE order_id = ? ORDER BY id")
            .bind(order_id).fetch_all(&self.db.pool).await?)
    }

    pub async fn orders(&self, q: &str, status: &str, user_id: Option<i64>) -> Result<Vec<Order>> {
        let like = format!("%{}%", q.trim());
        Ok(sqlx::query_as::<_, Order>(&format!("{ORDER_SELECT} WHERE (? = '' OR number LIKE ? OR user_id IN (SELECT id FROM users WHERE email LIKE ? OR name LIKE ?)) AND (? = '' OR status = ?) AND (? IS NULL OR user_id = ?) ORDER BY id DESC LIMIT 500"))
            .bind(q.trim()).bind(&like).bind(&like).bind(&like).bind(status).bind(status).bind(user_id).bind(user_id)
            .fetch_all(&self.db.pool).await?)
    }

    /// Revenue and counts for the dashboard and the passes page.
    pub async fn stats(&self) -> Result<serde_json::Value> {
        let (orders, revenue): (i64, i64) = sqlx::query_as(
            "SELECT COUNT(*), COALESCE(CAST(SUM(total_cents / fx_rate) AS INTEGER),0) FROM orders WHERE status = 'paid'",
        )
        .fetch_one(&self.db.pool)
        .await?;
        let now = crate::now();
        let (active_passes,): (i64,) = sqlx::query_as("SELECT COUNT(*) FROM entitlements WHERE scope IN ('site','category') AND status = 'active' AND (ends_at IS NULL OR ends_at > ?)").bind(&now).fetch_one(&self.db.pool).await?;
        let (active_subs, mrr): (i64, i64) = sqlx::query_as("SELECT COUNT(*), COALESCE(SUM(CASE WHEN s.interval = 'year' THEN p.price_cents / 12 ELSE p.price_cents END),0) FROM subscriptions s JOIN products p ON p.id = s.product_id WHERE s.status = 'active'").fetch_one(&self.db.pool).await?;
        let (expiring,): (i64,) = sqlx::query_as("SELECT COUNT(*) FROM entitlements WHERE scope IN ('site','category') AND status = 'active' AND ends_at > ? AND ends_at < ?").bind(&now).bind(add_days(&now, 7)).fetch_one(&self.db.pool).await?;
        let (churned,): (i64,) = sqlx::query_as("SELECT COUNT(*) FROM subscriptions WHERE status IN ('cancelled','ended') AND updated_at > ?").bind(add_days(&now, -30)).fetch_one(&self.db.pool).await?;
        Ok(
            serde_json::json!({ "orders": orders, "revenue_cents": revenue, "active_passes": active_passes, "active_subscriptions": active_subs, "mrr_cents": mrr, "expiring_7d": expiring, "churned_30d": churned }),
        )
    }

    /// The analytics report the Analytics wizard and the admin dashboard read: money in
    /// base-currency cents (orders paid in another currency divide by their `fx_rate`),
    /// months as `YYYY-MM`, newest last. Deterministic for the same data and `now`.
    pub async fn analytics(&self, months: i64) -> Result<serde_json::Value> {
        let months = months.clamp(1, 24);
        let now = crate::now();
        let since = add_days(&now, -30 * months);
        let month_start = format!("{}-01T00:00:00Z", &since[..7]);
        let stats = self.stats().await?;

        let by_month: Vec<(String, i64, i64)> = sqlx::query_as(
            "SELECT substr(paid_at, 1, 7), COUNT(*), COALESCE(CAST(SUM(total_cents / fx_rate) AS INTEGER),0) FROM orders WHERE status = 'paid' AND paid_at >= ? GROUP BY 1 ORDER BY 1",
        )
        .bind(&month_start)
        .fetch_all(&self.db.pool)
        .await?;
        let top: Vec<(String, String, String, i64, i64)> = sqlx::query_as(
            "SELECT p.slug, p.title, p.type, COALESCE(SUM(i.quantity),0), COALESCE(CAST(SUM(i.total_cents / o.fx_rate) AS INTEGER),0) FROM order_items i JOIN orders o ON o.id = i.order_id JOIN products p ON p.id = i.product_id WHERE o.status = 'paid' GROUP BY p.id ORDER BY 5 DESC, 4 DESC, p.slug LIMIT 20",
        )
        .fetch_all(&self.db.pool)
        .await?;
        let unsold: Vec<(String, String, String, i64)> = sqlx::query_as(
            "SELECT p.slug, p.title, p.type, p.price_cents FROM products p WHERE p.status = 'published' AND NOT EXISTS (SELECT 1 FROM order_items i JOIN orders o ON o.id = i.order_id WHERE i.product_id = p.id AND o.status = 'paid') ORDER BY p.slug LIMIT 50",
        )
        .fetch_all(&self.db.pool)
        .await?;
        let gateways: Vec<(String, i64, i64)> = sqlx::query_as(
            "SELECT gateway, COUNT(*), COALESCE(CAST(SUM(total_cents / fx_rate) AS INTEGER),0) FROM orders WHERE status = 'paid' GROUP BY gateway ORDER BY 2 DESC, 1",
        )
        .fetch_all(&self.db.pool)
        .await?;
        let coupons: Vec<(String, String, i64, i64, i64)> = sqlx::query_as(
            "SELECT c.code, c.kind, c.amount, c.uses, COALESCE((SELECT CAST(SUM(o.discount_cents / o.fx_rate) AS INTEGER) FROM orders o WHERE o.coupon = c.code AND o.status = 'paid'),0) FROM coupons c ORDER BY c.uses DESC, c.code",
        )
        .fetch_all(&self.db.pool)
        .await?;
        let playback: Vec<(String, String, i64, f64, i64)> = sqlx::query_as(
            "SELECT p.slug, p.title, COUNT(*), COALESCE(AVG(CASE WHEN s.duration_ms > 0 THEN 100.0 * MIN(s.position_ms, s.duration_ms) / s.duration_ms END),0), SUM(CASE WHEN s.last_seen >= ? THEN 1 ELSE 0 END) FROM playback_sessions s JOIN products p ON p.id = s.product_id GROUP BY p.id ORDER BY 3 DESC, p.slug LIMIT 20",
        )
        .bind(add_days(&now, -30))
        .fetch_all(&self.db.pool)
        .await?;
        let new_customers: Vec<(String, i64)> = sqlx::query_as(
            "SELECT substr(created_at, 1, 7), COUNT(*) FROM users WHERE role = 'customer' AND created_at >= ? GROUP BY 1 ORDER BY 1",
        )
        .bind(&month_start)
        .fetch_all(&self.db.pool)
        .await?;
        let (buyers, repeat_buyers): (i64, i64) = sqlx::query_as(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END),0) FROM (SELECT user_id, COUNT(*) AS n FROM orders WHERE status = 'paid' GROUP BY user_id)",
        )
        .fetch_one(&self.db.pool)
        .await?;
        let media_without_product: Vec<(String, String, String)> = sqlx::query_as(
            "SELECT m.uuid, m.type, COALESCE(m.title, '') FROM media m WHERE m.status = 'ready' AND NOT EXISTS (SELECT 1 FROM products p WHERE p.media_id = m.id) ORDER BY m.id LIMIT 50",
        )
        .fetch_all(&self.db.pool)
        .await?;

        Ok(serde_json::json!({
            "months": months,
            "generated_at": now,
            "totals": stats,
            "revenue_by_month": by_month.iter().map(|(m, n, c)| serde_json::json!({ "month": m, "orders": n, "revenue_cents": c })).collect::<Vec<_>>(),
            "top_products": top.iter().map(|(slug, title, t, units, c)| serde_json::json!({ "slug": slug, "title": title, "type": t, "units": units, "revenue_cents": c })).collect::<Vec<_>>(),
            "unsold_products": unsold.iter().map(|(slug, title, t, price)| serde_json::json!({ "slug": slug, "title": title, "type": t, "price_cents": price })).collect::<Vec<_>>(),
            "gateways": gateways.iter().map(|(g, n, c)| serde_json::json!({ "gateway": g, "orders": n, "revenue_cents": c })).collect::<Vec<_>>(),
            "coupons": coupons.iter().map(|(code, kind, amount, uses, given)| serde_json::json!({ "code": code, "kind": kind, "amount": amount, "uses": uses, "discount_given_cents": given })).collect::<Vec<_>>(),
            "playback": playback.iter().map(|(slug, title, n, pct, recent)| serde_json::json!({ "slug": slug, "title": title, "sessions": n, "completion_percent": (pct * 10.0).round() / 10.0, "sessions_30d": recent })).collect::<Vec<_>>(),
            "customers": {
                "new_by_month": new_customers.iter().map(|(m, n)| serde_json::json!({ "month": m, "accounts": n })).collect::<Vec<_>>(),
                "buyers": buyers, "repeat_buyers": repeat_buyers,
            },
            "media_without_product": media_without_product.iter().map(|(u, t, title)| serde_json::json!({ "uuid": u, "type": t, "title": title })).collect::<Vec<_>>(),
        }))
    }

    // ----- receipts -----

    pub async fn issue_receipt(
        &self,
        order_id: i64,
        prefix: &str,
        site_name: &str,
        footer: &str,
    ) -> Result<String> {
        if let Some(n) =
            sqlx::query_scalar::<_, String>("SELECT number FROM receipts WHERE order_id = ?")
                .bind(order_id)
                .fetch_optional(&self.db.pool)
                .await?
        {
            return Ok(n);
        }
        let Some(order) = self.order_by_id(order_id).await? else {
            bail!("order missing")
        };
        let items = self.items(order_id).await?;
        let (email, name): (String, String) =
            sqlx::query_as("SELECT email, name FROM users WHERE id = ?")
                .bind(order.user_id)
                .fetch_one(&self.db.pool)
                .await?;
        let now = crate::now();
        let year: i64 = now[..4].parse().unwrap_or(2026);
        let seq: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM receipts WHERE year = ?")
            .bind(year)
            .fetch_one(&self.db.pool)
            .await?;
        let number = format!(
            "{}-{year}-{:05}",
            if prefix.trim().is_empty() {
                "R"
            } else {
                prefix.trim()
            },
            seq + 1
        );
        let html = receipt_html(
            &number, &order, &items, &name, &email, site_name, footer, &now,
        );
        let pdf = receipt_pdf(
            &number, &order, &items, &name, &email, site_name, footer, &now,
        );
        sqlx::query("INSERT INTO receipts (order_id, number, year, html, pdf, issued_at) VALUES (?, ?, ?, ?, ?, ?)")
            .bind(order_id).bind(&number).bind(year).bind(&html).bind(&pdf).bind(&now).execute(&self.db.pool).await?;
        Ok(number)
    }

    pub async fn receipt(&self, order_id: i64) -> Result<Option<(String, String, Vec<u8>)>> {
        Ok(sqlx::query_as::<_, (String, String, Vec<u8>)>(
            "SELECT number, html, pdf FROM receipts WHERE order_id = ?",
        )
        .bind(order_id)
        .fetch_optional(&self.db.pool)
        .await?)
    }

    // ----- subscriptions -----

    #[allow(clippy::too_many_arguments)]
    pub async fn create_subscription(
        &self,
        user_id: i64,
        product_id: i64,
        order_id: Option<i64>,
        gateway: &str,
        external_id: Option<&str>,
        interval: &str,
        period_end: Option<&str>,
    ) -> Result<Subscription> {
        let now = crate::now();
        let uuid = uuid::Uuid::new_v4().to_string();
        sqlx::query("INSERT INTO subscriptions (uuid, user_id, product_id, order_id, gateway, external_id, interval, status, period_end, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)")
            .bind(&uuid).bind(user_id).bind(product_id).bind(order_id).bind(gateway).bind(external_id).bind(interval).bind(period_end).bind(&now).bind(&now)
            .execute(&self.db.pool).await?;
        Ok(self
            .subscription_by_uuid(&uuid)
            .await?
            .expect("just created"))
    }

    pub async fn subscription_by_uuid(&self, uuid: &str) -> Result<Option<Subscription>> {
        Ok(
            sqlx::query_as::<_, Subscription>(&format!("{SUB_SELECT} WHERE uuid = ?"))
                .bind(uuid)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn subscription_by_external(
        &self,
        gateway: &str,
        external_id: &str,
    ) -> Result<Option<Subscription>> {
        Ok(sqlx::query_as::<_, Subscription>(&format!(
            "{SUB_SELECT} WHERE gateway = ? AND external_id = ?"
        ))
        .bind(gateway)
        .bind(external_id)
        .fetch_optional(&self.db.pool)
        .await?)
    }

    pub async fn subscriptions_for(&self, user_id: i64) -> Result<Vec<Subscription>> {
        Ok(sqlx::query_as::<_, Subscription>(&format!(
            "{SUB_SELECT} WHERE user_id = ? ORDER BY id DESC"
        ))
        .bind(user_id)
        .fetch_all(&self.db.pool)
        .await?)
    }

    /// A renewal (gateway invoice paid): extends the entitlement to the new period end.
    pub async fn renew_subscription(&self, sub: &Subscription, period_end: &str) -> Result<()> {
        let now = crate::now();
        sqlx::query("UPDATE subscriptions SET status = 'active', period_end = ?, updated_at = ? WHERE id = ?")
            .bind(period_end).bind(&now).bind(sub.id).execute(&self.db.pool).await?;
        if let Some(p) = self.products.by_id(sub.product_id).await? {
            let scope_ref = String::new();
            self.entitlements
                .grant(Grant {
                    user_id: sub.user_id,
                    product_id: Some(p.id),
                    scope: if p.setting("scope") == "categories" {
                        "category"
                    } else {
                        "site"
                    },
                    scope_ref: &scope_ref,
                    source: "subscription",
                    source_ref: &sub.uuid,
                    starts_at: &now,
                    ends_at: Some(period_end),
                })
                .await?;
        }
        Ok(())
    }

    pub async fn set_subscription_status(
        &self,
        sub: &Subscription,
        status: &str,
        cancel_at_period_end: bool,
    ) -> Result<()> {
        sqlx::query("UPDATE subscriptions SET status = ?, cancel_at_period_end = ?, updated_at = ? WHERE id = ?")
            .bind(status).bind(cancel_at_period_end as i64).bind(crate::now()).bind(sub.id).execute(&self.db.pool).await?;
        if matches!(status, "cancelled" | "ended") && !cancel_at_period_end {
            self.entitlements
                .revoke_source("subscription", &sub.uuid)
                .await?;
            // The first period was granted by the order itself.
            if let Some(oid) = sub.order_id {
                if let Some(o) = self.order_by_id(oid).await? {
                    self.entitlements.revoke_source("order", &o.uuid).await?;
                }
            }
        }
        Ok(())
    }

    // ----- passes -----

    /// Expires overdue entitlements and records 7/3/1-day notices for holders of
    /// passes about to end. Runs from the worker once a day; cheap enough to run more.
    pub async fn pass_housekeeping(&self) -> Result<(u64, u64)> {
        let now = crate::now();
        let expired = sqlx::query("UPDATE entitlements SET status = 'expired', updated_at = ? WHERE status = 'active' AND ends_at IS NOT NULL AND ends_at <= ?")
            .bind(&now).bind(&now).execute(&self.db.pool).await?.rows_affected();
        let mut notices = 0;
        for days in [7, 3, 1] {
            let rows: Vec<(i64, i64)> = sqlx::query_as("SELECT id, user_id FROM entitlements WHERE scope IN ('site','category') AND status = 'active' AND ends_at > ? AND ends_at <= ?")
                .bind(&now).bind(add_days(&now, days)).fetch_all(&self.db.pool).await?;
            for (eid, uid) in rows {
                let r = sqlx::query("INSERT OR IGNORE INTO pass_notices (user_id, entitlement_id, days_left, created_at) VALUES (?, ?, ?, ?)")
                    .bind(uid).bind(eid).bind(days).bind(&now).execute(&self.db.pool).await?;
                notices += r.rows_affected();
            }
        }
        Ok((expired, notices))
    }

    pub async fn pass_notice_for(&self, user_id: i64) -> Result<Option<i64>> {
        Ok(sqlx::query_scalar("SELECT MIN(days_left) FROM pass_notices n JOIN entitlements e ON e.id = n.entitlement_id WHERE n.user_id = ? AND e.status = 'active'")
            .bind(user_id).fetch_optional(&self.db.pool).await?.flatten())
    }
}

pub fn add_days(now: &str, days: i64) -> String {
    let base = chrono::DateTime::parse_from_rfc3339(now)
        .map(|d| d.with_timezone(&chrono::Utc))
        .unwrap_or_else(|_| chrono::Utc::now());
    (base + chrono::Duration::days(days))
        .format("%Y-%m-%dT%H:%M:%SZ")
        .to_string()
}

pub fn money(cents: i64, currency: &str) -> String {
    let sign = if cents < 0 { "-" } else { "" };
    let c = cents.abs();
    format!("{sign}{currency} {}.{:02}", c / 100, c % 100)
}

fn esc(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

#[allow(clippy::too_many_arguments)]
fn receipt_html(
    number: &str,
    o: &Order,
    items: &[OrderItem],
    name: &str,
    email: &str,
    site: &str,
    footer: &str,
    issued: &str,
) -> String {
    let mut rows = String::new();
    for i in items {
        rows.push_str(&format!(
            "<tr><td>{} × {}</td><td class=\"r\">{}</td></tr>",
            i.quantity,
            esc(&i.title),
            money(i.total_cents, &o.currency)
        ));
    }
    let mut totals = format!(
        "<tr><td>Subtotal</td><td class=\"r\">{}</td></tr>",
        money(o.subtotal_cents, &o.currency)
    );
    if o.discount_cents > 0 {
        totals.push_str(&format!(
            "<tr><td>Discount{}</td><td class=\"r\">-{}</td></tr>",
            o.coupon
                .as_deref()
                .map(|c| format!(" ({})", esc(c)))
                .unwrap_or_default(),
            money(o.discount_cents, &o.currency)
        ));
    }
    if o.tax_cents > 0 {
        totals.push_str(&format!(
            "<tr><td>{} ({}.{:02}%)</td><td class=\"r\">{}</td></tr>",
            esc(&o.tax_name),
            o.tax_rate_bp / 100,
            o.tax_rate_bp % 100,
            money(o.tax_cents, &o.currency)
        ));
    }
    totals.push_str(&format!(
        "<tr class=\"total\"><td>Total paid</td><td class=\"r\">{}</td></tr>",
        money(o.total_cents, &o.currency)
    ));
    format!("<!doctype html><html><head><meta charset=\"utf-8\"><title>Receipt {n}</title><style>body{{font:14px/1.5 system-ui,sans-serif;color:#222;max-width:680px;margin:32px auto;padding:0 16px}}table{{width:100%;border-collapse:collapse}}td{{padding:6px 0;border-bottom:1px solid #eee}}.r{{text-align:right}}.total td{{font-weight:700;border-top:2px solid #222}}.muted{{color:#666}}</style></head><body><h1>{site}</h1><h2>Receipt {n}</h2><p class=\"muted\">Order {on} · issued {issued}<br>Billed to {name} &lt;{email}&gt;{country}</p><table>{rows}{totals}</table><p class=\"muted\">{footer}</p></body></html>",
        n = esc(number), site = esc(site), on = esc(&o.number), issued = &issued[..10], name = esc(name), email = esc(email),
        country = if o.country.is_empty() { String::new() } else { format!(" · {}", esc(&o.country)) }, footer = esc(footer))
}

#[allow(clippy::too_many_arguments)]
fn receipt_pdf(
    number: &str,
    o: &Order,
    items: &[OrderItem],
    name: &str,
    email: &str,
    site: &str,
    footer: &str,
    issued: &str,
) -> Vec<u8> {
    let mut d = crate::pdf::Document::new(&format!("Receipt {number}"));
    d.text(18.0, true, site);
    d.text(14.0, true, &format!("Receipt {number}"));
    d.text(
        10.0,
        false,
        &format!("Order {} - issued {}", o.number, &issued[..10]),
    );
    d.text(
        10.0,
        false,
        &format!(
            "Billed to {name} <{email}>{}",
            if o.country.is_empty() {
                String::new()
            } else {
                format!(" - {}", o.country)
            }
        ),
    );
    d.space(8.0);
    d.rule();
    for i in items {
        d.row(
            11.0,
            false,
            &format!("{} x {}", i.quantity, i.title),
            &money(i.total_cents, &o.currency),
        );
    }
    d.rule();
    d.row(
        11.0,
        false,
        "Subtotal",
        &money(o.subtotal_cents, &o.currency),
    );
    if o.discount_cents > 0 {
        d.row(
            11.0,
            false,
            &format!(
                "Discount{}",
                o.coupon
                    .as_deref()
                    .map(|c| format!(" ({c})"))
                    .unwrap_or_default()
            ),
            &format!("-{}", money(o.discount_cents, &o.currency)),
        );
    }
    if o.tax_cents > 0 {
        d.row(
            11.0,
            false,
            &format!(
                "{} ({}.{:02}%)",
                o.tax_name,
                o.tax_rate_bp / 100,
                o.tax_rate_bp % 100
            ),
            &money(o.tax_cents, &o.currency),
        );
    }
    d.row(12.0, true, "Total paid", &money(o.total_cents, &o.currency));
    d.space(16.0);
    d.paragraph(9.0, footer);
    d.finish()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn coupon(kind: &str, amount: i64) -> Coupon {
        Coupon {
            id: 1,
            code: "SAVE".into(),
            kind: kind.into(),
            amount,
            currency: String::new(),
            max_uses: 0,
            uses: 0,
            expires_at: None,
            status: "active".into(),
            created_at: String::new(),
        }
    }

    #[test]
    fn totals_are_deterministic_and_rounded() {
        let t = totals(4900, None, None);
        assert_eq!(t.total_cents, 4900);
        let t = totals(
            4900,
            Some(&coupon("percent", 10)),
            Some(&TaxRate {
                id: 1,
                country: "DE".into(),
                region: String::new(),
                name: "VAT".into(),
                rate_bp: 1900,
            }),
        );
        assert_eq!(t.discount_cents, 490);
        assert_eq!(t.tax_cents, 838); // 4410 * 19% = 837.9 → 838
        assert_eq!(t.total_cents, 5248);
        let t = totals(1000, Some(&coupon("fixed", 5000)), None);
        assert_eq!((t.discount_cents, t.total_cents), (1000, 0));
        let t = totals(333, Some(&coupon("percent", 50)), None);
        assert_eq!(t.discount_cents, 167); // 166.5 rounds up
    }

    async fn seed(db: &Db) -> (Commerce, i64, Product, Product) {
        let c = Commerce::new(db.clone());
        let now = crate::now();
        sqlx::query("INSERT INTO users (uuid, email, name, role, status, created_at, updated_at) VALUES ('u1','u@x.io','Una','customer','active',?,?)").bind(&now).bind(&now).execute(&db.pool).await.unwrap();
        for (uuid, slug, t, title, price, settings) in [
            ("p1", "film", "video", "Film", 4900, "{}"),
            (
                "p2",
                "pass",
                "site_pass",
                "Pass",
                9900,
                r#"{"validity":"days","days":"30","scope":"site"}"#,
            ),
        ] {
            sqlx::query("INSERT INTO products (uuid, slug, type, title, price_cents, currency, settings, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'USD', ?, 'published', ?, ?)")
                .bind(uuid).bind(slug).bind(t).bind(title).bind(price).bind(settings).bind(&now).bind(&now).execute(&db.pool).await.unwrap();
        }
        let p = Products::new(db.clone());
        let film = p.by_slug("film").await.unwrap().unwrap();
        let pass = p.by_slug("pass").await.unwrap().unwrap();
        (c, 1, film, pass)
    }

    #[tokio::test]
    async fn cart_order_pay_receipt_and_refund() {
        let db = Db::memory().await.unwrap();
        let (c, uid, film, pass) = seed(&db).await;
        // Guest cart, then adoption on login merges with the user's old cart.
        let old = c.cart("old-device", Some(uid)).await.unwrap();
        c.add(&old, &pass, 1).await.unwrap();
        let guest = c.cart("guest", None).await.unwrap();
        c.add(&guest, &film, 5).await.unwrap();
        let cart = c.cart("guest", Some(uid)).await.unwrap();
        let lines = c.lines(&cart).await.unwrap();
        assert_eq!(lines.len(), 2, "merged");
        assert_eq!(lines[0].quantity, 1, "media products cap at one copy");
        c.create_coupon("save10", "percent", 10, 1, None)
            .await
            .unwrap();
        c.set_tax_rate("de", "VAT", 1900).await.unwrap();
        c.set_country(&cart, "de").await.unwrap();
        c.set_coupon(&cart, "save10").await.unwrap();
        assert!(c.set_coupon(&cart, "nope").await.is_err());
        let cart = c.cart("guest", Some(uid)).await.unwrap();
        let t = c
            .cart_totals(&cart, &c.lines(&cart).await.unwrap())
            .await
            .unwrap();
        assert_eq!(t.subtotal_cents, 14800);
        assert_eq!(t.discount_cents, 1480);
        let order = c.create_order(&cart, uid, "USD").await.unwrap();
        assert!(order.number.starts_with("ORD-"));
        assert_eq!(order.total_cents, t.total_cents);
        let ents = Entitlements::new(db.clone());
        let now = crate::now();
        assert!(!ents
            .check(uid, &crate::entitlements::Subject::Product(film.id), &now)
            .await
            .unwrap());
        assert!(c
            .mark_paid(&order, "test", Some("t_1"), "R", "Demo", "Thanks")
            .await
            .unwrap());
        let order = c.order_by_id(order.id).await.unwrap().unwrap();
        assert!(
            !c.mark_paid(&order, "test", Some("t_1"), "R", "Demo", "Thanks")
                .await
                .unwrap(),
            "idempotent"
        );
        assert!(ents
            .check(uid, &crate::entitlements::Subject::Product(film.id), &now)
            .await
            .unwrap());
        // Site pass grants everything for 30 days.
        let e = ents.for_user(uid).await.unwrap();
        assert!(e.iter().any(|e| e.scope == "site" && e.ends_at.is_some()));
        // Coupon used up; cart emptied; receipt issued with PDF.
        assert!(c.valid_coupon("SAVE10").await.unwrap().is_none());
        assert!(c.lines(&cart).await.unwrap().is_empty());
        let (number, html, pdf) = c.receipt(order.id).await.unwrap().unwrap();
        assert!(
            number.starts_with("R-") && html.contains("Total paid") && pdf.starts_with(b"%PDF")
        );
        assert!(html.contains("VAT (19.00%)"));
        // The analytics report reads the paid order, its coupon and the unsold products.
        sqlx::query("INSERT INTO playback_sessions (uuid, user_id, product_id, media_id, player, position_ms, duration_ms, started_at, last_seen) VALUES ('ps1', ?, ?, NULL, 'video', 45000, 60000, ?, ?)")
            .bind(uid).bind(film.id).bind(&now).bind(&now).execute(&db.pool).await.unwrap();
        let a = c.analytics(12).await.unwrap();
        assert_eq!(a["totals"]["orders"], 1);
        assert_eq!(a["revenue_by_month"][0]["orders"], 1);
        assert_eq!(a["revenue_by_month"][0]["month"], now[..7]);
        assert_eq!(a["top_products"][0]["slug"], "pass", "dearest first");
        assert_eq!(a["top_products"][1]["units"], 1);
        assert!(a["unsold_products"].as_array().unwrap().is_empty());
        assert_eq!(a["gateways"][0]["gateway"], "test");
        assert_eq!(a["coupons"][0]["code"], "SAVE10");
        assert_eq!(a["coupons"][0]["uses"], 1);
        assert_eq!(a["coupons"][0]["discount_given_cents"], 1480);
        assert_eq!(a["playback"][0]["completion_percent"], 75.0);
        assert_eq!(a["playback"][0]["sessions_30d"], 1);
        assert_eq!(a["customers"]["buyers"], 1);
        assert_eq!(a["customers"]["repeat_buyers"], 0);
        assert_eq!(a["customers"]["new_by_month"][0]["accounts"], 1);
        // Refund revokes.
        c.mark_refunded(&order, Some("re_1"), "customer request")
            .await
            .unwrap();
        assert!(!ents
            .check(uid, &crate::entitlements::Subject::Product(film.id), &now)
            .await
            .unwrap());
        assert_eq!(
            c.order_by_id(order.id).await.unwrap().unwrap().status,
            "refunded"
        );
        let stats = c.stats().await.unwrap();
        assert_eq!(stats["orders"], 0);
        let a = c.analytics(3).await.unwrap();
        assert_eq!(
            a["unsold_products"].as_array().unwrap().len(),
            2,
            "refunded orders do not count as sales"
        );
        assert!(a["revenue_by_month"].as_array().unwrap().is_empty());
    }

    #[tokio::test]
    async fn passes_expire_and_notify() {
        let db = Db::memory().await.unwrap();
        let (c, uid, _film, _pass) = seed(&db).await;
        let ents = Entitlements::new(db.clone());
        let now = crate::now();
        let soon = add_days(&now, 2);
        let gone = add_days(&now, -1);
        ents.grant(Grant {
            user_id: uid,
            product_id: None,
            scope: "site",
            scope_ref: "",
            source: "manual",
            source_ref: "a",
            starts_at: &now,
            ends_at: Some(&soon),
        })
        .await
        .unwrap();
        ents.grant(Grant {
            user_id: uid,
            product_id: None,
            scope: "site",
            scope_ref: "",
            source: "manual",
            source_ref: "b",
            starts_at: &gone,
            ends_at: Some(&gone),
        })
        .await
        .unwrap();
        let (expired, notices) = c.pass_housekeeping().await.unwrap();
        assert_eq!(
            (expired, notices),
            (1, 2),
            "7 and 3 day notices for the pass ending in 2 days"
        );
        assert_eq!(c.pass_notice_for(uid).await.unwrap(), Some(3));
        assert_eq!(c.pass_housekeeping().await.unwrap(), (0, 0));
    }
}
