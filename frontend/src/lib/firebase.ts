import { getApp, getApps, initializeApp, type FirebaseApp } from "firebase/app";
import { getAuth, inMemoryPersistence, initializeAuth, type Auth } from "firebase/auth";
import { getFirestore, type Firestore } from "firebase/firestore";

/** MM-146: the public Firebase web config (not a secret -- access is enforced
 * by firestore.rules and the custom token's claims). Inlined at build time by
 * next.config.ts from NEXT_PUBLIC_FIREBASE_* or App Hosting's
 * FIREBASE_WEBAPP_CONFIG. Empty on a host without it: the app then polls. */
const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY ?? "",
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "",
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "",
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID ?? "",
};

export const firebaseConfigured = Boolean(
  firebaseConfig.apiKey && firebaseConfig.projectId && firebaseConfig.appId,
);

let clients: { auth: Auth; db: Firestore } | null = null;

/** One Firebase app per browser tab. Auth keeps its session in memory only,
 * so a different MarginMaestro user signing in on the same browser never
 * inherits the previous user's Firebase identity (and scope). */
export function firebaseClients(): { auth: Auth; db: Firestore } {
  if (clients) return clients;
  const app: FirebaseApp = getApps().length ? getApp() : initializeApp(firebaseConfig);
  let auth: Auth;
  try {
    auth = initializeAuth(app, { persistence: inMemoryPersistence });
  } catch {
    auth = getAuth(app); // already initialized (e.g. fast refresh)
  }
  clients = { auth, db: getFirestore(app) };
  return clients;
}
