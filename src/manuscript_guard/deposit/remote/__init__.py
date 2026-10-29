"""What `deposit` sends, and only when the author asks: Zenodo's DOI reserved, a bundle staged
as a draft at Zenodo or as a private OSF project, and a Zenodo draft published.

`http` sends one request and reads its answer, with the token in a header and nowhere else;
`zenodo` and `osf` speak each host's API; `receipts` keeps what each host answered, in
`deposit/receipts/` and `deposit/history.yaml`; `command` is what `deposit --reserve-doi`,
`--stage` and `--publish` run. No gate imports the clients; G4 reads the receipts.
"""
