"""Holdings pricing: public instrument search + quotes, normalised to GBP.

Split along the encryption line — this package only ever touches public price
data (plaintext), never a user's units. See service.py for the request-time
refresh that snapshots priced assets into (encrypted) valuations.
"""
