---
name: tracking-specialist
description: Conversion tracking architect for GTM, GA4, Google Ads, Meta CAPI, and server-side tagging. Use when implementing new tracking, diagnosing conversion discrepancies, migrating from UA to GA4, or setting up enhanced conversions. Triggered by mentions of pixel, tag manager, attribution, conversion tracking, or data layer.
---

# Tracking & Measurement Specialist

## When to Use This Skill

Use this skill when working on the brand's measurement infrastructure or advising on:

- New tracking implementation for site launches or redesigns
- Diagnosing conversion count discrepancies between platforms (GA4 vs Google Ads vs CRM)
- Setting up enhanced conversions or server-side tagging
- GTM container audit (bloated containers, firing issues, consent gaps)
- Migration from Universal Analytics to GA4
- Conversion action restructuring (changing what you optimize toward)
- Privacy compliance review (Consent Mode v2, GDPR, CCPA)
- Building a measurement plan before major campaign launches

## Core Principles

**Bad tracking is worse than no tracking.** A miscounted conversion doesn't just waste data — it actively misleads bidding algorithms into optimizing for the wrong outcomes.

### The Golden Rules
1. **Single source of truth**: One dataLayer event should feed all platforms
2. **Test before deploy**: Use GTM Preview mode and Tag Assistant for every change
3. **Version control**: Export GTM container JSON after every significant change
4. **Cross-reference constantly**: Compare platform counts weekly; investigate >3% discrepancies

## Platform-Specific Implementation

### Google Tag Manager

**Container Architecture**
- Use folders to organize tags by platform (Google, Meta, TikTok, etc.)
- Implement tag sequencing: Consent Mode first, then marketing tags
- Use variables for dynamic values (conversion IDs, pixel IDs) to avoid hardcoding

**Trigger Design**
- Prefer custom events over pageview triggers for conversion actions
- Use exception triggers to block tags on error pages or admin areas
- Implement DOM ready triggers for elements loaded asynchronously

### GA4 Ecommerce Events

For ecom brands, implement this event sequence:

```javascript
dataLayer.push({
  event: 'purchase',
  ecommerce: {
    transaction_id: 'T_12345',
    value: 25.42,
    currency: 'USD',
    items: [{
      item_id: 'SKU_12345',
      item_name: 'Product Name',
      item_category: 'Category',
      price: 25.42,
      quantity: 1
    }]
  }
});
```

**Required events**: `view_item`, `add_to_cart`, `begin_checkout`, `purchase`
**Recommended custom events**: `sign_up`, `lead_form_submit`, `phone_click`

### Google Ads Enhanced Conversions

1. Capture user-provided data at conversion time (email, phone)
2. Hash using SHA-256 before sending
3. Match rate target: 70%+
4. Verify via Google Ads Diagnostics tab

### Meta Conversions API (CAPI)

**Server-Side Event Requirements**
- Send the same events as browser Pixel (purchase, lead, etc.)
- Include `event_id` for deduplication (must match browser event)
- Hash user data consistently (SHA-256, lowercase, trim whitespace)
- Test via Meta Event Manager before going live

**Deduplication Check**
```
Browser Pixel event_id: abc123
Server CAPI event_id:   abc123
Result: Single counted conversion ✓
```

## Debugging & QA Workflow

### Pre-Launch Checklist
- [ ] Tag Assistant shows all tags firing on correct triggers
- [ ] GA4 DebugView shows events with correct parameters
- [ ] Meta Event Manager shows CAPI events in Test Events tab
- [ ] Google Ads shows conversions in the conversion action
- [ ] Purchase events include transaction_id, value, and currency
- [ ] Consent Mode v2 signals are passing (ad_storage, analytics_storage)

### Ongoing Monitoring
- **Weekly**: Compare conversion counts across GA4, Google Ads, Meta, and CRM
- **Monthly**: Review GTM container for unused tags and triggers (bloat increases load time)
- **Quarterly**: Audit dataLayer implementation after any site changes

## Common Issues & Fixes

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| GA4 conversions > Google Ads | Attribution window difference | Check attribution model alignment |
| Meta CAPI double-counting | Missing event_id match | Ensure browser + server event_id identical |
| Purchase value discrepancy | Tax/shipping inclusion mismatch | Standardize value calculation in dataLayer |
| Tags not firing on SPA | Pageview triggers only | Switch to history change or custom event triggers |
| Consent Mode blocking all tags | Default denial without update | Implement consent banner → update consent state |

## Applying This Playbook

- Route new tracking events through the agent's existing event-intake pipeline rather than building parallel tracking
- Respect user consent state before firing marketing tags
- Retain raw event data for audit trails and debugging

## Success Metrics

- **Tracking Accuracy**: <3% discrepancy between ad platform and analytics conversion counts
- **Tag Firing Reliability**: 99.5%+ successful tag fires on target events
- **Enhanced Conversion Match Rate**: 70%+
- **CAPI Deduplication**: Zero double-counted conversions
- **Page Speed Impact**: Tag implementation adds <200ms to page load time
- **Consent Mode Coverage**: 100% of tags respect consent signals
