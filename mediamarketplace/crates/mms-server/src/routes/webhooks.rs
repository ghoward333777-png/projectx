//! Inbound gateway webhooks: verified, idempotent by event id.

use crate::app::AppState;
use crate::errors::AppResult;
use axum::body::Bytes;
use axum::extract::{Path, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use mms_core::gateways::Event;

pub async fn receive(
    State(state): State<AppState>,
    Path(gateway): Path<String>,
    headers: HeaderMap,
    body: Bytes,
) -> AppResult<Response> {
    let Some(gw) = crate::routes::shop::gateway_named(&state, &gateway).await? else {
        return Ok((StatusCode::NOT_FOUND, "unknown gateway").into_response());
    };
    let hdrs: Vec<(String, String)> = headers
        .iter()
        .map(|(k, v)| (k.as_str().to_string(), v.to_str().unwrap_or("").to_string()))
        .collect();
    let (event_id, event) = match gw.webhook(&hdrs, &body).await {
        Ok(x) => x,
        Err(e) => {
            tracing::warn!(gateway = %gateway, error = %e, "webhook rejected");
            return Ok((StatusCode::BAD_REQUEST, e.to_string()).into_response());
        }
    };
    // Idempotency: a replayed event id is acknowledged and ignored.
    let inserted = sqlx::query("INSERT OR IGNORE INTO gateway_events (gateway, event_id, kind, payload, received_at) VALUES (?, ?, ?, ?, ?)")
        .bind(gw.name()).bind(&event_id).bind(format!("{event:?}").chars().take(40).collect::<String>()).bind(String::from_utf8_lossy(&body).chars().take(20_000).collect::<String>()).bind(mms_core::now())
        .execute(&state.db.pool).await?.rows_affected();
    if inserted == 0 {
        return Ok((StatusCode::OK, "duplicate").into_response());
    }
    match event {
        Event::Paid {
            order_uuid,
            external_id,
            subscription_id,
            period_end,
        } => {
            let order = match order_uuid {
                Some(u) => state.commerce.order_by_uuid(&u).await?,
                None => {
                    state
                        .commerce
                        .order_by_external(gw.name(), &external_id)
                        .await?
                }
            };
            if let Some(order) = order {
                crate::routes::shop::complete_paid(
                    &state,
                    &order,
                    gw.name(),
                    Some(&external_id),
                    subscription_id.as_deref(),
                    period_end.as_deref(),
                )
                .await?;
            }
        }
        Event::Refunded { external_id } => {
            if let Some(order) = state
                .commerce
                .order_by_external(gw.name(), &external_id)
                .await?
            {
                if order.status == "paid" {
                    state
                        .commerce
                        .mark_refunded(&order, None, "refunded at the gateway")
                        .await?;
                    crate::routes::shop::emit(
                        &state,
                        "order.refunded",
                        serde_json::json!({ "order": order.uuid, "number": order.number }),
                    )
                    .await?;
                }
            }
        }
        Event::SubscriptionRenewed {
            subscription_id,
            period_end,
        } => {
            if let Some(sub) = state
                .commerce
                .subscription_by_external(gw.name(), &subscription_id)
                .await?
            {
                state.commerce.renew_subscription(&sub, &period_end).await?;
                crate::routes::shop::emit(
                    &state,
                    "subscription.renewed",
                    serde_json::json!({ "subscription": sub.uuid, "period_end": period_end }),
                )
                .await?;
            }
        }
        Event::SubscriptionEnded { subscription_id } => {
            if let Some(sub) = state
                .commerce
                .subscription_by_external(gw.name(), &subscription_id)
                .await?
            {
                state
                    .commerce
                    .set_subscription_status(&sub, "ended", false)
                    .await?;
                crate::routes::shop::emit(
                    &state,
                    "subscription.ended",
                    serde_json::json!({ "subscription": sub.uuid }),
                )
                .await?;
            }
        }
        Event::Ignored(_) => {}
    }
    Ok((StatusCode::OK, "ok").into_response())
}
