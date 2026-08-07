from coaching_contracts import SessionState


class InvalidStateTransition(ValueError):
    pass


ALLOWED_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.CREATED: {
        SessionState.UPLOADING,
        SessionState.CANCELLED,
        SessionState.DELETE_PENDING,
    },
    SessionState.UPLOADING: {
        SessionState.UPLOADED,
        SessionState.FAILED,
        SessionState.CANCELLED,
        SessionState.DELETE_PENDING,
    },
    SessionState.UPLOADED: {
        SessionState.TRANSCRIBING,
        SessionState.CANCELLED,
        SessionState.DELETE_PENDING,
    },
    SessionState.TRANSCRIBING: {
        SessionState.RECONCILING,
        SessionState.TRANSCRIPT_READY,
        SessionState.RETRY_PENDING,
        SessionState.FAILED,
        SessionState.CANCELLED,
        SessionState.DELETE_PENDING,
    },
    SessionState.RECONCILING: {
        SessionState.TRANSCRIPT_READY,
        SessionState.AWAITING_REVIEW,
        SessionState.COMPLETE,
        SessionState.RETRY_PENDING,
        SessionState.FAILED,
        SessionState.CANCELLED,
        SessionState.DELETE_PENDING,
    },
    SessionState.TRANSCRIPT_READY: {
        SessionState.RECONCILING,
        SessionState.EXTRACTING,
        SessionState.AWAITING_REVIEW,
        SessionState.CANCELLED,
        SessionState.DELETE_PENDING,
    },
    SessionState.EXTRACTING: {
        SessionState.AWAITING_REVIEW,
        SessionState.RETRY_PENDING,
        SessionState.FAILED,
        SessionState.CANCELLED,
        SessionState.DELETE_PENDING,
    },
    SessionState.AWAITING_REVIEW: {
        SessionState.COMPLETE,
        SessionState.RECONCILING,
        SessionState.EXTRACTING,
        SessionState.DELETE_PENDING,
    },
    SessionState.COMPLETE: {
        SessionState.AWAITING_REVIEW,
        SessionState.RECONCILING,
        SessionState.DELETE_PENDING,
    },
    SessionState.RETRY_PENDING: {
        SessionState.TRANSCRIBING,
        SessionState.RECONCILING,
        SessionState.EXTRACTING,
        SessionState.FAILED,
        SessionState.CANCELLED,
        SessionState.DELETE_PENDING,
    },
    SessionState.FAILED: {
        SessionState.RETRY_PENDING,
        SessionState.DELETE_PENDING,
    },
    SessionState.CANCELLED: {
        SessionState.RETRY_PENDING,
        SessionState.DELETE_PENDING,
    },
    SessionState.DELETE_PENDING: {SessionState.DELETED},
    SessionState.DELETED: set(),
}


def transition(record, target: SessionState) -> None:
    current = SessionState(record.state)
    if target == current:
        return
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransition(f"cannot transition {current} -> {target}")
    record.state = target.value
