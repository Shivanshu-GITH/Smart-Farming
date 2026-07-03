from app.economics import mandi


async def test_price_falls_back_to_estimate_without_key():
    info = await mandi.get_price("tomato")
    assert info["source"] == "estimate"
    assert info["price_per_kg"] == 12  # economics.json fallback


async def test_price_unknown_crop_returns_none():
    info = await mandi.get_price("does-not-exist")
    assert info["price_per_kg"] is None


async def test_get_prices_maps_all_ids():
    prices = await mandi.get_prices(["tomato", "banana"])
    assert set(prices) == {"tomato", "banana"}
    assert all(p["source"] == "estimate" for p in prices.values())
