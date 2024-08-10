import falcon.testing as testing


def test_things(asgi, util):
    suffix = '_asgi' if asgi else ''
    things = util.load_module(f'examples/things{suffix}.py')

    resp = testing.simulate_get(things.app, '/things')

    assert resp.status_code == 200
    assert resp.text == (
        '\nTwo things awe me most, the starry sky above me and the moral law within me.'
        '\n\n    ~ Immanuel Kant\n\n'
    )


def test_things_advanced(asgi, util):
    suffix = '_asgi' if asgi else ''
    advanced = util.load_module(f'examples/things_advanced{suffix}.py')

    # NOTE(vytas): The ASGI example explicitly requires Content-Length
    #   (its middleware errors out otherwise with 400).
    #   Should we change this?
    resp1 = testing.simulate_get(
        advanced.app, '/1337/things', headers={'Content-Length': '0'}
    )
    assert resp1.status_code == 401

    resp2 = testing.simulate_get(
        advanced.app,
        '/1337/things',
        headers={'Authorization': 'custom-token', 'Content-Length': '0'},
    )
    assert resp2.status_code == 200
    assert len(resp2.json) == 1
    assert resp2.json[0]['color'] == 'green'