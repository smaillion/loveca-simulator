from loveca.cards.validation import validate_card_type


def test_known_card_type_is_valid():
    assert validate_card_type("member") == []


def test_card_type_validation_normalizes_case_and_spacing():
    assert validate_card_type(" Live ") == []


def test_unknown_card_type_returns_field_error():
    errors = validate_card_type("support")

    assert len(errors) == 1
    assert errors[0].field == "card_type"
    assert "support" in errors[0].message
