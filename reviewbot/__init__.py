"""A pull-request review bot governed by HarnessWeaver.

The model reads the change and writes the review; the harness decides what the
bot may do along the way. It can comment, but a maintainer confirms every
approval, and it can never merge.
"""
