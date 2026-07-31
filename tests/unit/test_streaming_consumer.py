from unittest.mock import MagicMock

import pytest
from confluent_kafka import KafkaError
from pydantic import BaseModel

from streaming.consumer import ConsumerError, EventConsumer, decode


class _Payload(BaseModel):
    ticker: str
    price: float


def _make_message(value: bytes, error: object | None = None) -> MagicMock:
    msg = MagicMock()
    msg.error.return_value = error
    msg.value.return_value = value
    return msg


def test_subscribes_to_given_topics_on_construction() -> None:
    mock_consumer = MagicMock()

    EventConsumer(
        topics=["market.prices", "market.events"], group_id="test", consumer=mock_consumer
    )

    mock_consumer.subscribe.assert_called_once_with(["market.prices", "market.events"])


def test_poll_returns_none_when_no_message_available() -> None:
    mock_consumer = MagicMock()
    mock_consumer.poll.return_value = None
    consumer = EventConsumer(topics=["market.prices"], group_id="test", consumer=mock_consumer)

    assert consumer.poll(1.0) is None


def test_poll_returns_message_on_success() -> None:
    mock_consumer = MagicMock()
    msg = _make_message(b'{"ticker": "AAPL", "price": 150.0}')
    mock_consumer.poll.return_value = msg
    consumer = EventConsumer(topics=["market.prices"], group_id="test", consumer=mock_consumer)

    assert consumer.poll(1.0) is msg


def test_poll_returns_none_on_partition_eof() -> None:
    mock_consumer = MagicMock()
    err = MagicMock()
    err.code.return_value = KafkaError._PARTITION_EOF
    mock_consumer.poll.return_value = _make_message(b"", error=err)
    consumer = EventConsumer(topics=["market.prices"], group_id="test", consumer=mock_consumer)

    assert consumer.poll(1.0) is None


def test_poll_raises_on_real_broker_error() -> None:
    mock_consumer = MagicMock()
    err = MagicMock()
    err.code.return_value = KafkaError._ALL_BROKERS_DOWN
    mock_consumer.poll.return_value = _make_message(b"", error=err)
    consumer = EventConsumer(topics=["market.prices"], group_id="test", consumer=mock_consumer)

    with pytest.raises(ConsumerError):
        consumer.poll(1.0)


def test_commit_delegates_to_underlying_consumer_synchronously() -> None:
    mock_consumer = MagicMock()
    consumer = EventConsumer(topics=["market.prices"], group_id="test", consumer=mock_consumer)
    msg = MagicMock()

    consumer.commit(msg)

    mock_consumer.commit.assert_called_once_with(message=msg, asynchronous=False)


def test_context_manager_closes_underlying_consumer() -> None:
    mock_consumer = MagicMock()

    with EventConsumer(
        topics=["market.prices"], group_id="test", consumer=mock_consumer
    ) as consumer:
        assert consumer is not None

    mock_consumer.close.assert_called_once()


def test_decode_parses_message_value_into_model() -> None:
    msg = _make_message(b'{"ticker": "AAPL", "price": 150.0}')

    payload = decode(msg, _Payload)

    assert payload == _Payload(ticker="AAPL", price=150.0)
