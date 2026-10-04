# Supabase database trust

`prod-supabase.cer` is the public Supabase Root 2021 CA certificate, downloaded over verified HTTPS from
https://supabase-downloads.s3-ap-southeast-1.amazonaws.com/prod/ssl/prod-ca-2021.crt.

SHA-256 fingerprint: `807025ad50d4ed219d2c9c7d299c004f824eb00cf7f65afef607d07b72e6cafa`.
Expires: April 26, 2031. This file contains no private key or account credential.

The backend adds this CA to the system trust store for Supabase database hostnames and still verifies the
server hostname. `DATABASE_SSL_CA_FILE` can supply a replacement CA file when Supabase rotates certificates
or for a custom database hostname. TLS certificate checking is never bypassed.
