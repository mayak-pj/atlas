from atlas.features.hello.logic import greeting


def test_greeting():
    assert greeting() == "Привет!"
    assert greeting("Иванов") == "Привет, Иванов!"
