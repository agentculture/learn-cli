// Site-side re-export of the shared Terms/Privacy version, mirroring
// ../lib/content.ts's role as the typed loader every page imports through.
// Both policy pages (src/pages/terms/, src/pages/privacy/) import from this
// local path rather than reaching across the repo boundary themselves — the
// fact that the value actually lives in ../../../shared/terms-version.mjs is
// an implementation detail of this one file.
//
// See ../../../shared/terms-version.mjs for why that file is a plain ES
// module (not JSON) and for the re-consent contract TERMS_VERSION backs.
export { TERMS_VERSION, TERMS_EFFECTIVE_DATE } from "../../../shared/terms-version.mjs";
