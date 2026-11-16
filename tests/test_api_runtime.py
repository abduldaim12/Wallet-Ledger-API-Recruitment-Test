import inspect

from api import create_app


def test_database_routes_use_sync_handlers():
    app = create_app()
    routes = {
        route.path: route.endpoint
        for route in app.routes
        if hasattr(route, "endpoint")
    }

    assert not inspect.iscoroutinefunction(routes["/credit"])
    assert not inspect.iscoroutinefunction(routes["/debit"])
    assert not inspect.iscoroutinefunction(routes["/balance/{user_id}"])
