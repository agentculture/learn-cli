// Worker-side re-export of the shared Terms/Privacy version. This file
// exists (rather than every worker module reaching across the repo boundary
// itself) so worker code always imports from a local `./terms.js` path,
// matching the shape of every other `src/*.js` module here — the fact that
// the value actually lives in ../../../shared/terms-version.mjs is an
// implementation detail of this one file.
//
// See ../../../shared/terms-version.mjs for why that file is a plain ES
// module and not JSON, and for the re-consent contract TERMS_VERSION backs
// (plan task t6, spec honesty condition h2). Wired in by t5: consent.js
// renders the requirement from it and POST /api/consent/accept stamps the
// consent row's `terms_version` with this exact value. Consulting it for
// version-mismatch (re-consent) is t6's job — extend
// consent.js#consentSatisfiesCurrentTerms.
export { TERMS_VERSION, TERMS_EFFECTIVE_DATE } from "../../../shared/terms-version.mjs";
