use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};

/// Converts any error into a 500 while logging the cause; never leaks internals to the client.
pub struct AppError(pub anyhow::Error);

impl<E: Into<anyhow::Error>> From<E> for AppError {
    fn from(e: E) -> Self {
        Self(e.into())
    }
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        tracing::error!(error = %self.0, "request failed");
        // Debug builds show the cause to speed up development; release builds never leak it.
        let body = if cfg!(debug_assertions) {
            format!("Something went wrong: {:#}", self.0)
        } else {
            "Something went wrong. The error has been logged.".to_string()
        };
        (StatusCode::INTERNAL_SERVER_ERROR, body).into_response()
    }
}

pub type AppResult<T> = Result<T, AppError>;
