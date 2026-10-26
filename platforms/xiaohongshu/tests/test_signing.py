from collector._signer import SessionManager, Xhshow


def test_signer_fixed_input_structure() -> None:
    client = Xhshow()
    cookies = {
        "a1": "1234567890123456789012345678901234567890123456789012",
        "web_session": "fixture",
        "webId": "fixture",
    }
    headers = client.sign_headers_post(
        "/api/sns/web/v1/homefeed",
        cookies=cookies,
        payload={"num": 10, "cursor_score": ""},
        timestamp=1789020994.763,
        session=SessionManager(),
        x_rap=True,
    )
    decoded = client.decode_xs(headers["x-s"])
    assert headers["x-t"] == "1789020994763"
    assert headers["x-s"].startswith("XYS_")
    assert headers["x-rap-param"]
    assert decoded["x0"] == "4.3.5"
    assert decoded["x1"] == "xhs-pc-web"
    assert decoded["x2"] == "Windows"
    assert decoded["x3"].startswith("mns0301_")
