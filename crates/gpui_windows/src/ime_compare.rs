use std::{
    fmt,
    sync::{OnceLock, mpsc::{self, SyncSender}},
    time::{SystemTime, UNIX_EPOCH},
};

use windows::Win32::UI::WindowsAndMessaging::{
    MSG, WM_IME_COMPOSITION, WM_IME_ENDCOMPOSITION, WM_IME_STARTCOMPOSITION, WM_KEYDOWN,
    WM_SYSKEYDOWN,
};

static WRITER: OnceLock<Option<SyncSender<String>>> = OnceLock::new();

pub(crate) fn record(stage: &str, details: fmt::Arguments<'_>) {
    if let Some(writer) = WRITER.get_or_init(|| {
        std::env::var_os("GPUI_IME_COMPARE")?;
        let (writer, events) = mpsc::sync_channel::<String>(4096);
        std::thread::Builder::new()
            .name("ime-trace".into())
            .spawn(move || {
                while let Ok(event) = events.recv() {
                    eprintln!("{event}");
                }
            })
            .ok()?;
        Some(writer)
    }) {
        let timestamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_nanos();
        if writer.try_send(format!("[ime-compare] ns={timestamp} {stage} {details}")).is_err() {
            // A dropped event means this trace cannot establish the ordering.
            DROPPED.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        }
    }
}

static DROPPED: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

pub(crate) fn dispatch(from: &str, msg: &MSG) {
    if matches!(msg.message, WM_KEYDOWN | WM_SYSKEYDOWN | WM_IME_COMPOSITION | WM_IME_ENDCOMPOSITION | WM_IME_STARTCOMPOSITION) {
        let dropped = DROPPED.load(std::sync::atomic::Ordering::Relaxed);
        let flags = if msg.message == WM_IME_COMPOSITION { msg.lParam.0 } else { 0 };
        record("dispatch", format_args!("from={from} msg={:#x} tick={} flags={flags:#x} dropped={dropped}", msg.message, msg.time));
    }
}
