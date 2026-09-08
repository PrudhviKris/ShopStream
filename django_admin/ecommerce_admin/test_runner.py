"""Test runner that creates tables for the unmanaged store models.

The analytics models are managed=False in production (the FastAPI service owns
those tables). Inside the isolated test database they must exist, so the runner
flips them to managed while the test database is being set up.
"""
from django.test.runner import DiscoverRunner


class UnmanagedModelTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        from django.apps import apps

        self._unmanaged = [m for m in apps.get_models() if not m._meta.managed]
        for model in self._unmanaged:
            model._meta.managed = True
        super().setup_test_environment(**kwargs)

    def teardown_test_environment(self, **kwargs):
        super().teardown_test_environment(**kwargs)
        for model in self._unmanaged:
            model._meta.managed = False
