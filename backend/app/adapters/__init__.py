from . import ats, portals
from .base import Blocked, Unsupported  # noqa: F401
from .generic import generic

ADAPTERS = {
    "greenhouse": ats.greenhouse,
    "lever": ats.lever,
    "ashby": ats.ashby,
    "smartrecruiters": ats.smartrecruiters,
    "workable": ats.workable,
    "recruitee": ats.recruitee,
    "personio": ats.personio,
    "workday": portals.workday,
    "eightfold": portals.eightfold,
    "generic": generic,
}
