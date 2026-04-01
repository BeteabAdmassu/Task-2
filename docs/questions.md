# Business Logic Questions Log

## 1. Authentication & Rate Limiting

1. **Rate Limiting Scope**
   - **Question**: The prompt says "10 login attempts per 10 minutes per account plus IP." Does "plus" mean both constraints apply simultaneously (AND), or either one triggers lockout (OR)?
   - **My Understanding**: Both constraints are enforced independently. If either the account OR the IP exceeds 10 attempts in 10 minutes, the login is blocked. This provides defense against both credential stuffing (one IP, many accounts) and distributed brute force (many IPs, one account).
   - **Solution**: Track login attempts in a `login_attempts` table with both `username` and `ip_address`. On each login attempt, check both `COUNT(*) WHERE username = ? AND attempted_at > NOW() - 10min` and `COUNT(*) WHERE ip_address = ? AND attempted_at > NOW() - 10min`. Block if either exceeds 10.

2. **Session Behavior on Role Change**
   - **Question**: When an admin changes a user's role, should existing sessions for that user be invalidated immediately or continue with the old role until expiry?
   - **My Understanding**: For security, role changes should take effect on the next request. Active sessions are not forcefully terminated, but the role is re-read from the database on each request rather than cached in the session.
   - **Solution**: Store only `user_id` in the session, not the role. Load the user's current role from the database on every authenticated request via middleware.

---

## 2. Visit State Machine

3. **No-Show Eligibility**
   - **Question**: Can "No-Show" be applied to a "Booked" visit (patient never arrived) or only to "Checked In" (patient arrived but wasn't seen)?
   - **My Understanding**: No-Show applies to visits that are past their appointment time and the patient never arrived. It can be applied to "Booked" visits after the scheduled time has passed, and also to "Checked In" visits where the patient left before being seen.
   - **Solution**: Allow transition to No-Show from both "Booked" (if appointment time has passed) and "Checked In" states. For "Booked" → No-Show, validate that `slot.start_time + slot.duration < current_time`.

4. **Pending Payment State**
   - **Question**: When is "Pending Payment" used vs. skipped? The prompt mentions it but doesn't detail payment processing.
   - **My Understanding**: Since the platform is offline with no payment gateway, "Pending Payment" is a manual state for clinics that collect copays at check-in. Front Desk marks the visit as "Pending Payment" if payment is needed, then transitions to "Checked In" once payment is collected. If no payment is needed, Booked goes directly to Checked In.
   - **Solution**: Make the Booked → Pending Payment transition optional. Front Desk sees both "Check In" and "Collect Payment" buttons on Booked visits. "Collect Payment" transitions to Pending Payment; "Check In" transitions directly to Checked In.

5. **Admin Override Cancellation**
   - **Question**: Can an admin cancel a visit that is already in "Seen" state?
   - **My Understanding**: "Seen" is a terminal state representing a completed visit. Canceling a completed visit would create data integrity issues with assessments and audit trails. Admin overrides should only work on active (non-terminal) states.
   - **Solution**: Admin cancel override is available for Booked, Pending Payment, and Checked In — not for Seen, Canceled, or No-Show. Terminal states are truly terminal.

---

## 3. Scheduling & Reservation Holds

6. **Hold Limit per Patient**
   - **Question**: Can a patient hold multiple slots at once, or only one at a time?
   - **My Understanding**: Allowing unlimited holds enables slot hoarding. A maximum of 2 simultaneous holds balances patient flexibility (comparing two time options) with fairness.
   - **Solution**: Before creating a hold, check `COUNT(*) FROM reservations WHERE patient_id = ? AND status = 'held' AND expires_at > NOW()`. Reject if count ≥ 2 with message "You can hold a maximum of 2 slots at a time."

7. **Hold Expiry Mechanism**
   - **Question**: Should holds be expired by a background job (exact timing) or lazily on access (slight delay but simpler)?
   - **My Understanding**: A hybrid approach — background job for cleanup plus lazy check on access — provides both accuracy and reliability. The background job runs every minute; the lazy check catches any holds that expired between job runs.
   - **Solution**: APScheduler job runs every 60 seconds: `UPDATE reservations SET status = 'expired' WHERE status = 'held' AND expires_at < NOW()`. Additionally, every slot availability query filters out holds where `expires_at < NOW()` regardless of their stored status.

8. **Bulk Schedule vs. Holidays**
   - **Question**: If a bulk schedule generation covers a date range that includes holidays, should slots be generated on holidays and then blocked, or simply skipped?
   - **My Understanding**: Slots should not be generated on holidays at all. Generating and then blocking creates unnecessary data and potential confusion.
   - **Solution**: During bulk generation, query the `holidays` table for the date range and exclude those dates from slot creation. Return a summary showing how many slots were generated and how many dates were skipped due to holidays.

---

## 4. Assessments & Risk Stratification

9. **Combined Risk Level Calculation**
   - **Question**: How should individual assessment scores combine into the overall risk level? Is the overall level the maximum of individual levels, or is there a weighted formula?
   - **My Understanding**: The overall risk level is the highest severity among all individual assessments. If any single assessment scores "High," the overall level is "High." This is a conservative, patient-safety-first approach.
   - **Solution**: Evaluate each assessment independently against its thresholds. The overall risk level = `max(individual_risk_levels)` where High > Moderate > Low. The explanation snapshot lists every rule that contributed, with contributing answers highlighted.

10. **Assessment Versioning on Template Change**
    - **Question**: If a PHQ-9 template is updated (e.g., question wording changes), what happens to in-progress drafts?
    - **My Understanding**: In-progress drafts should be invalidated if the template version changes, since answers may no longer align with the questions. Completed assessments are immutable and always retain their original template version.
    - **Solution**: Store `template_version` in both drafts and results. On draft load, compare `draft.template_version` with current template version. If mismatched, discard the draft and start fresh with a notification: "This assessment has been updated. Please start again."

---

## 5. Coverage Zones & Delivery

11. **Overlapping ZIP Codes Across Zones**
    - **Question**: Can the same ZIP code belong to multiple zones (e.g., overlapping distance bands)?
    - **My Understanding**: No — each ZIP code maps to exactly one active zone. This avoids ambiguity in fee calculation and delivery window determination.
    - **Solution**: Enforce uniqueness via a UNIQUE constraint on `zone_zip_codes.zip_code` scoped to active zones. On zone creation/update, check for conflicts: `SELECT zone_id FROM zone_zip_codes zc JOIN coverage_zones cz ON zc.zone_id = cz.id WHERE zc.zip_code IN (?) AND cz.is_active = 1 AND cz.id != ?`.

12. **Zone Deactivation Impact on Active Orders**
    - **Question**: If a zone is deactivated, what happens to deliveries already confirmed in that zone?
    - **My Understanding**: Deactivation is forward-looking. Already-confirmed deliveries proceed as planned. New orders to that zone are rejected.
    - **Solution**: Zone deactivation sets `is_active = 0` but does not cascade to existing records. Delivery eligibility checks filter on `is_active = 1`. Audit log records who deactivated the zone and when.

---

## 6. Security & Privacy

13. **Anti-Replay Window Duration**
    - **Question**: Why 5 minutes? What if server and client clocks are slightly out of sync?
    - **My Understanding**: 5 minutes provides tolerance for minor clock drift (typical NTP sync keeps clocks within 1-2 seconds) while still limiting replay attack windows. Since this is a LAN-only system, clock sync should be tight.
    - **Solution**: Accept timestamps within ±5 minutes of server time. The signed timestamp uses `HMAC-SHA256(server_secret, timestamp + nonce + endpoint)`. Nonces are stored in `signed_nonces` table and rejected on reuse within the window. Nonces older than 10 minutes are pruned.

14. **Data Deletion Scope**
    - **Question**: When a patient deletes their account, should assessment scores be preserved (de-identified) or fully deleted?
    - **My Understanding**: Clinical data has legal retention requirements. Assessment scores and visit records are preserved in de-identified form (no patient name, just anonymized ID). This preserves aggregate data for reporting while removing PII.
    - **Solution**: Replace user fields: `username → 'ANON-' + SHA256(user_id + salt)[:12]`, `full_name → NULL`, `phone → NULL`, `all encrypted fields → NULL`. Keep: visit dates, assessment scores, state transitions, audit log entries (with anonymized actor). Delete: session records, login attempts, reminders, assessment drafts.

---

## 7. Reminders & Reassessments

15. **Duplicate Reminder Prevention**
    - **Question**: If a patient has an overdue reassessment AND an upcoming visit, should they get one reminder or two?
    - **My Understanding**: They should get two separate reminders — one for the reassessment and one for the visit — since they are distinct actionable items. But the same type of reminder should not be generated twice for the same entity.
    - **Solution**: Before creating a reminder, check for existing non-expired reminders of the same type and entity: `SELECT id FROM reminders WHERE patient_id = ? AND type = ? AND related_entity_id = ? AND status NOT IN ('expired', 'dismissed', 'acted_on')`. Skip creation if one exists.

16. **Reassessment Interval Start Date**
    - **Question**: Does the 90-day reassessment clock start from the last completed assessment, or from the reminder creation date?
    - **My Understanding**: From the last completed assessment. If a patient completed a PHQ-9 on January 1, the next reassessment is due April 1, regardless of when (or if) a reminder was generated or dismissed.
    - **Solution**: Query: `SELECT MAX(submitted_at) FROM assessment_results WHERE patient_id = ? AND template_id = ?`. If `MAX(submitted_at) + interval_days < NOW()`, generate a reassessment reminder.

---

## 8. Observability

17. **Anomaly Alert: "New Device/IP" Definition**
    - **Question**: What constitutes a "new device session"? The platform has no device fingerprinting.
    - **My Understanding**: Since there's no device fingerprinting on a LAN system, "unusual new-device sessions" translates to "login from a new IP address." Compare the login IP against the user's last 5 session IPs. If the IP has never been seen, trigger an alert.
    - **Solution**: On successful login, query `SELECT DISTINCT ip_address FROM sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT 5`. If the current IP is not in this list and the list has ≥ 2 entries (avoid false positives on first logins), create an anomaly alert of type `new_ip_session`.

18. **Slow Query Threshold Applicability**
    - **Question**: Does the 500ms slow-query threshold apply to SQLite queries specifically, or to full endpoint response time?
    - **My Understanding**: It applies to individual database query execution time, not full endpoint time. An endpoint might make 5 fast queries totaling 400ms — that's not a slow query issue, it's an optimization opportunity tracked differently.
    - **Solution**: Wrap the database execution layer with timing. If any single query exceeds the threshold, log it to `slow_queries` with the sanitized query text (parameters replaced with `?`) and duration. Full endpoint response time is logged separately in structured request logs.
