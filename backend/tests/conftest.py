"""Tests run as user 1 (the admin / single-user owner) unless they switch with tenancy.as_user()."""
from app import tenancy

tenancy.set_user(1)
