from src.handlers.download_handlers import _clean_download_target


def test_axinstagram_rewritten_to_real_instagram():
    url = "https://www.axinstagram.com/reel/Dcj2jkXTKEv/?stkn=MTh0YTVuYXd6bXZjaw=="
    assert _clean_download_target(url) == "https://www.instagram.com/reel/Dcj2jkXTKEv/"


def test_axinstagram_without_www_also_rewritten():
    url = "https://axinstagram.com/p/Cabc123XYZ/"
    assert _clean_download_target(url) == "https://www.instagram.com/p/Cabc123XYZ/"


def test_real_instagram_url_untouched():
    url = "https://www.instagram.com/reel/Dcj2jkXTKEv/"
    assert _clean_download_target(url) == url
