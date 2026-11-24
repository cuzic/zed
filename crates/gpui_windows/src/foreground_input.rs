/// Drain the foreground queue without waiting. The peek callback selects
/// keyboard/mouse input when its argument is false and IME messages when true.
pub(crate) fn drain_foreground_input<T>(
    mut peek: impl FnMut(bool) -> Option<T>,
    mut dispatch: impl FnMut(T),
) {
    while let Some(message) = peek(false) {
        dispatch(message);
    }
}

#[cfg(test)]
mod tests {
    use std::cell::{Cell, RefCell};
    use std::collections::VecDeque;

    use super::drain_foreground_input;

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
            |ime_only| {
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
