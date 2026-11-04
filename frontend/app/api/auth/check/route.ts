import { NextRequest, NextResponse } from "next/server";
import crypto from "crypto";

function signSessionToken(secret: string): string {
  return crypto.createHmac("sha256", secret).update("aegis_authenticated_v1").digest("hex");
}

export async function GET(req: NextRequest) {
  const serverPasscode = process.env.APP_PASSCODE || process.env.NEXT_PUBLIC_APP_PASSCODE;

  // If no passcode is configured, authentication is not enforced
  if (!serverPasscode) {
    return NextResponse.json({ authenticated: true, requiresAuth: false });
  }

  const expectedToken = signSessionToken(serverPasscode);
  const sessionCookie = req.cookies.get("auth_session");
  const legacyPasscodeCookie = req.cookies.get("auth_passcode");

  if (
    sessionCookie?.value === expectedToken ||
    legacyPasscodeCookie?.value === serverPasscode
  ) {
    return NextResponse.json({ authenticated: true, requiresAuth: true });
  }

  return NextResponse.json({ authenticated: false, requiresAuth: true });
}
