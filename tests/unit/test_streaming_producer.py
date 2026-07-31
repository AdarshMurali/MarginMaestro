import json
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from streaming.producer import EventProducer, ProducerDeliveryError


class _Payload(BaseModel):
    ticker: str
    price: float


def test_publish_serializes_model_and_produces_with_key() -> None:
    mock_producer = MagicMock()
    producer = EventProducer(producer=mock_producer)

    producer.publish("market.prices", _Payload(ticker="AAPL", price=150.0), key="AAPL")

    args, kwargs = mock_producer.produce.call_args
    assert args[0] == "market.prices"
    assert kwargs["key"] == b"AAPL"
    assert json.loads(kwargs["value"]) == {"ticker": "AAPL", "price": 150.0}
    mock_producer.poll.assert_called_once_with(0)


def test_publish_without_key_sends_none_key() -> None:
    mock_producer = MagicMock()
    producer = EventProducer(producer=mock_producer)

    producer.publish("market.prices", _Payload(ticker="AAPL", price=150.0))

    _, kwargs = mock_producer.produce.call_args
    assert kwargs["key"] is None


def test_flush_raises_on_delivery_failure() -> None:
    mock_producer = MagicMock()
    producer = EventProducer(producer=mock_producer)
    producer.publish("market.prices", _Payload(ticker="AAPL", price=150.0))
    callback = mock_producer.produce.call_args.kwargs["callback"]

    callback("boom", None)

    with pytest.raises(ProducerDeliveryError, match="1 message"):
        producer.flush()


def test_flush_does_not_raise_when_no_delivery_errors() -> None:
    mock_producer = MagicMock()
    mock_producer.flush.return_value = 0
    producer = EventProducer(producer=mock_producer)
    producer.publish("market.prices", _Payload(ticker="AAPL", price=150.0))
    callback = mock_producer.produce.call_args.kwargs["callback"]

    callback(None, MagicMock())

    assert producer.flush() == 0


def test_flush_clears_errors_so_they_are_not_raised_twice() -> None:
    mock_producer = MagicMock()
    producer = EventProducer(producer=mock_producer)
    producer.publish("market.prices", _Payload(ticker="AAPL", price=150.0))
    callback = mock_producer.produce.call_args.kwargs["callback"]
    callback("boom", None)

    with pytest.raises(ProducerDeliveryError):
        producer.flush()

    producer.flush()
