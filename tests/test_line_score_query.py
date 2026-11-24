import re


def test_分數指令格式():
    樣式 = r"(\d{2,3})分以上"
    assert re.fullmatch(樣式, "80分以上").group(1) == "80"
    assert re.fullmatch(樣式, "75分以上")
    assert not re.fullmatch(樣式, "2330")


def test_有高分明細查詢():
    import notify
    assert callable(notify.高分明細查詢)
