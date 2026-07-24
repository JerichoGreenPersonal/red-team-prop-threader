from review_prep.cl_parser import is_delivery_comment, parse_cls_from_comment


def test_parse_source_art_preflight_and_wip():
    text = (
        "Source Art CL is 11288616\n"
        "Preflight CL is 11288606\n"
        "WIP CL 11290000\n"
    )
    parsed = parse_cls_from_comment(text)
    assert [(p.label, p.number) for p in parsed] == [
        ("Source Art", 11288616),
        ("Preflight", 11288606),
        ("WIP", 11290000),
    ]


def test_unknown_label_still_parses():
    parsed = parse_cls_from_comment("Lighting CL is 555")
    assert len(parsed) == 1
    assert parsed[0].label == "Lighting"
    assert parsed[0].policy_key == "Unknown"


def test_internal_comment_is_not_delivery():
    assert is_delivery_comment("looks good, thanks") is False
    assert is_delivery_comment("Source Art CL is 1") is True
