// Worker-side re-export of the shared Terms/Privacy version. This file
// exists (rather than every worker module reaching across the repo boundary
// itself) so worker code always imports from a local `./terms.js` path,
// matching the shape of every other `src/*.js` module here — the fact that
// the value actually lives in ../../../shared/terms-version.mjs is an
// implementation detail of this one file.
//
// See ../../../shared/terms-version.mjs for why that file is a plain ES
// module and not JSON, and for the re-consent contract TERMS_VERSION backs
// (plan task t6, spec honesty condition h2). Not wired into any route yet —
// this task (t1) only establishes the shared source; recording/consulting
// `consent.terms_version` is t5/t6's job.
export { TERMS_VERSION, TERMS_EFFECTIVE_DATE } from "../../../shared/terms-version.mjs";
