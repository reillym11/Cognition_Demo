# Self-review: reuse the browser binding across overlapping sign-ins

- `backend/app/foundation/auth.py` (protected): `/api/auth/login` reuses the browser's existing `itp_login` binding
  cookie instead of minting a new one and deleting that browser's earlier pending states. Reported symptom: switching
  roles in a Codespace ended in `state_mismatch`, because a second `/login` (double click, back button, retried
  request) rotated the binding and deleted the state of the flow the browser then completed.
- Unchanged: state is still single-use and deleted on callback; binding still ties the state to the browser
  (HttpOnly, path `/api/auth`, cleared on success); per-client cap (10) and the 10-minute TTL still bound storage;
  nonce and PKCE unchanged.
- Test: `test_overlapping_signins_in_one_browser_share_binding_and_stay_valid`.
