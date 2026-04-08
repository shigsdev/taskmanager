# Post-Deploy UAT Checklist

Run through this after every Railway deploy. Takes ~2 minutes.
Skip sections for features you didn't change.

---

## 1. Health & Login

- [ ] Visit `/healthz` — should return `{"status": "ok"}` with all checks passing
- [ ] Visit `/` — should redirect to login page (if not already logged in)
- [ ] Click "Sign in with Google" — should complete OAuth and land on task board
- [ ] Verify your email shows in the nav bar

## 2. Tasks

- [ ] Create a task via the quick capture bar
- [ ] Task appears in Inbox
- [ ] Open task detail panel — edit title, add a note
- [ ] Move task to Today tier
- [ ] Move task to This Week tier
- [ ] Complete a task (checkbox)
- [ ] Delete a task

## 3. Goals

- [ ] Navigate to Goals page
- [ ] Create a new goal
- [ ] Link a task to the goal
- [ ] Verify progress bar updates
- [ ] Delete the test goal

## 4. Projects

- [ ] Check project filter dropdown on task board
- [ ] Assign a task to a project
- [ ] Filter by that project — only its tasks show

## 5. Import

- [ ] Navigate to Import page
- [ ] Paste OneNote text mode: paste `- Test task one\n- Test task two`
- [ ] Parse → review screen shows candidates
- [ ] Cancel (don't actually import)
- [ ] Upload .docx mode: verify file picker accepts .docx only
- [ ] Upload Excel mode: verify file picker accepts .xlsx only

## 6. Scan

- [ ] Navigate to Scan page
- [ ] Verify camera/upload UI loads
- [ ] (Optional) Upload a test image — verify candidates appear

## 7. Review

- [ ] Navigate to Review page
- [ ] If stale tasks exist, step through keep/freeze/delete flow
- [ ] If no stale tasks, verify "nothing to review" message

## 8. Print

- [ ] Navigate to Print page
- [ ] Verify Today and This Week tasks render
- [ ] (Optional) Ctrl+P — verify print layout looks clean

## 9. Settings

- [ ] Navigate to Settings page
- [ ] Verify service status badges (Google OAuth, SendGrid, etc.)
- [ ] Verify app stats (task count, goal count)
- [ ] Click "Send Digest Now" — verify success or expected error

## 10. Digest Email

- [ ] After clicking Send Digest, check your inbox
- [ ] Verify email contains today's tasks and overdue items
- [ ] Verify no sensitive info (API keys, tokens) in email body

## 11. PWA

- [ ] On iPhone Safari, visit the app
- [ ] Share → Add to Home Screen
- [ ] Open from home screen — should launch without Safari URL bar
- [ ] Navigate between pages — app stays full-screen

## 12. Mobile

- [ ] Open app on phone (or resize browser to mobile width)
- [ ] Verify nav is usable, no horizontal scroll
- [ ] Tap a task — detail panel opens full-screen
- [ ] Swipe gestures work (if applicable)

## 13. Logout

- [ ] Click Log out
- [ ] Verify redirect to login page
- [ ] Visit `/` — should redirect to login (session cleared)
