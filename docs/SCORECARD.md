# Living Scorecard

Last updated: 2026-05-22

## DX Metrics

| Metric | Pixeltable | Supabase | Convex | Modal |
|--------|-----------|----------|--------|-------|
| Lines of Code | 368 | 617 | 434 | 676 |
| Source Files | 14 | 9 | 9 | 11 |
| Languages | 1 | 2 | 1 | 2 |
| External Services | 1 | 2 | 2 | 3 |
| Env Vars | 1 | 4 | 2 | 5 |

## Journey Scorecard

| Phase | Pixeltable | Supabase | Convex | Modal |
|-------|-----------|----------|--------|-------|
| 1. Install & Setup | Strong | Okay | Okay | Okay |
| 2. Define Schema | Strong | Okay | Okay | Gap |
| 3. Ingest Data | Strong | Okay | Okay | Gap |
| 4. Add Embeddings | Strong | Weak | Weak | Okay |
| 5. Semantic Search | Strong | Okay | Okay | Gap |
| 6. Serve API | Strong | Okay | Okay | Okay |
| 7. Dev Loop | Strong | Okay | Okay | Okay |
| 8. Deploy to Prod | Gap | Okay | Strong | Strong |
| 9. Schema Evolution | Weak | Weak | Weak | Okay |
| 10. Monitor & Scale | Gap | Okay | Strong | Strong |

## Changelog

### 2026-05-22 -- Initial benchmark

- Pixeltable v0.6+, Supabase JS v2.49, Convex v1.39, Modal latest
- All implementations use OpenAI text-embedding-3-small (1536d)
- Fixture: 3 text docs, 3 images, 5 test queries
