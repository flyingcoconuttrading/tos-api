After every code change session, always end your response with:

## Git Commands
```bash
git add -A
git commit -m "<filled in summary of all changes made>"
git push origin main
```

## Changes Made
- file.py: what changed and why
- file2.py: what changed and why

## After every session
1. Update tests/test_plan.md with tests for all changes made
2. Update tests/smoke_test.py with any new endpoints
3. Run smoke_test.py and confirm all pass before git commit
4. Output git commands with filled commit message
5. Output changelog: file | what changed | why
