pub(crate) enum ForegroundMessageKind {
    Ime,
    Input,
}

/// Drain foreground input while keeping IME notifications ahead of the next key.
pub(crate) fn drain_foreground_input<T>(
    mut peek: impl FnMut(ForegroundMessageKind) -> Option<T>,
    mut dispatch: impl FnMut(T),
) {
    loop {
        // A key can queue a composition result. Process it before retrieving
        // another key because that key can overwrite the IMM result string.
        while let Some(message) = peek(ForegroundMessageKind::Ime) {
            dispatch(message);
        }

        let Some(message) = peek(ForegroundMessageKind::Input) else {
            break;
        };
        dispatch(message);
    }
}

#[cfg(test)]
mod tests {
    use std::cell::{Cell, RefCell};
    use std::collections::VecDeque;

    use super::{ForegroundMessageKind, drain_foreground_input};

    #[test]
    fn dispatches_ime_commit_before_the_next_key() {
        #[derive(Clone, Copy)]
        enum Message {
            StartNextComposition,
            ImeCommit,
            ContinueComposition,
        }

        let queue = RefCell::new(VecDeque::from([
            Message::StartNextComposition,
            Message::ContinueComposition,
        ]));
        let commit = Cell::new(None);
        let delivered = Cell::new(None);

        drain_foreground_input(
            |kind| {
                let ime_only = matches!(kind, ForegroundMessageKind::Ime);
                let mut queue = queue.borrow_mut();
                let index = queue
                    .iter()
                    .position(|message| matches!(message, Message::ImeCommit) == ime_only)?;
                queue.remove(index)
            },
            |message| match message {
                Message::StartNextComposition => {
                    // Translating the first key commits the old composition and
                    // queues its notification outside the keyboard input filter.
                    commit.set(Some("今"));
                    queue.borrow_mut().push_back(Message::ImeCommit);
                }
                Message::ImeCommit => delivered.set(commit.take()),
                Message::ContinueComposition => commit.set(None),
            },
        );

        // The normal event loop handles any messages left after the drain.
        if let Some(Message::ImeCommit) = queue.into_inner().pop_front() {
            delivered.set(commit.take());
        }

        assert_eq!(delivered.get(), Some("今"));
    }
}
