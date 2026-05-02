# Screenshots

This directory holds grading evidence screenshots.

## Required screenshot: hubspot_contact_novapay.png

Run the agent against one synthetic prospect end-to-end.
Take a screenshot of the resulting HubSpot contact record
showing all fields populated and the enrichment_timestamp
field present. Save as `screenshots/hubspot_contact_novapay.png`

### Steps to generate

1. Ensure your `.env` is configured with `HUBSPOT_ACCESS_TOKEN`,
   `OPENROUTER_API_KEY`, and `LIVE_MODE=false`.

2. Run the happy path:
   ```bash
   python main.py
   ```

3. Open HubSpot and navigate to the Jordan Kim contact at NovaPay Technologies
   (contact ID `476928855768`, `jordan.kim@novapaytechnologies.com`).

4. In the contact record:
   - Click **Actions → Edit properties**
   - Search for and add: `enrichment_timestamp`, `signal_source`,
     `icp_segment`, `ai_maturity_score`, `signal_confidence`
   - Click **Save**

5. Take a screenshot showing all fields populated and the
   `enrichment_timestamp` field visible. Save it here as
   `hubspot_contact_novapay.png`.

### What graders will verify

- Contact exists with non-null `firstname`, `lastname`, `email`, `company`, `jobtitle`
- `enrichment_timestamp` is present and a recent ISO 8601 datetime
- `signal_source` = `tenacious_enrichment_pipeline_v1`
- `icp_segment`, `ai_maturity_score`, `signal_confidence` are populated
- At least one activity note is visible in the contact timeline

### Note on custom properties

If `enrichment_timestamp` is not visible as a contact column, the
custom HubSpot properties may need to be created first. Run:

```bash
python scripts/setup_hubspot_properties.py
```

This requires `crm.schemas.contacts.write` scope on the private app token.
To add the scope: HubSpot developer portal → your app → Auth → Scopes.
