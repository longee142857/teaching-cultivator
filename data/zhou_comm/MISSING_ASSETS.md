# Missing delivery assets

This PR is a **directory + README + placeholders** only.

The real pack was not available to the agent that opened the PR:

| Source tried | Result |
|--------------|--------|
| GitHub Release / draft `zhou_comm_atoms_delivery.tar.gz` on `teaching-cultivator` | No releases (published or draft) |
| Workspace, `/tmp`, artifacts | No `zhou_comm*` files |
| Other reachable longee142857 repos / Gmail / public web | No pack |

**Required to close the blocker:** extract `zhou_comm_atoms_delivery.tar.gz` into `data/zhou_comm/` so that `zhou_comm.db` (~6MB sqlite) and the companion files overwrite these placeholders.

Until then, `python query_api.py demo` is expected to fail with exit code 2.
