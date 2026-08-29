import { createContext } from "react";

/**
 * Google Identity Services script-load state (LEGACY — auth-vault-credentials
 * PR3). The Google auth flow was removed from the app: LoginScreen no longer
 * renders the GIS button and App.tsx no longer wraps the tree in
 * GoogleOAuthProvider. This context is kept only so the file still compiles
 * without the removed `getGoogleNonce`/`startGoogleSession` API functions;
 * nothing imports it anymore. PR4 deletes this file together with the
 * remaining Google artifacts (useGoogleAuth.ts, google-auth-api.test.ts).
 */
export const GoogleScriptErrorContext = createContext<boolean>(false);