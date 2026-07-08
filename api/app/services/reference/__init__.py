"""Published reference facts (UK limits, curated benchmark rates).

Deliberately a code module, not a table: values change by a human editing the
file and deploying — never a runtime fetch, and never a DB row a background
job refreshes (background jobs can't read user data here, and reference data
doesn't need one).
"""
