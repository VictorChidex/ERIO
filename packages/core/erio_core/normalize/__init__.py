"""Turn what a source said into canonical job fields (spec section 6).

Every function here is pure: text in, structured value out. The ingest
service applies them to raw postings and writes canonical jobs.
"""
