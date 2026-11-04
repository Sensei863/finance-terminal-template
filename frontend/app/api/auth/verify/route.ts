import { NextRequest, NextResponse } from "next/server";
import crypto from "crypto";

function signSessionToken(secret: string): string {
  return crypto.createHmac("sha256", secret).update("aegis_authenticated_v1").digest("hex");
}

export async function POST(req: NextRequest) {
  try {
    const { passcode } = await req.json();
    const serverPasscode = process.env.APP_PASSCODE || process.env.NEXT_PUBLIC_APP_PASSCODE;

    // If no passcode is configured, allow access
    if (!serverPasscode) {
      const response = NextResponse.json({ success: true, message: "No passcode required" });
      response.cookies.set("auth_session", "unlocked", {
        path: "/",
        maxAge: 60 * 60 * 24 * 30, // 30 days
        sameSite: "lax",
        httpOnly: true,
      });
      return response;
    }

    if (typeof passcode === "string" && passcode === serverPasscode) {
      const response = NextResponse.json({ success: true });
      const token = signSessionToken(serverPasscode);
      response.cookies.set("auth_session", token, {
        path: "/",
        maxAge: 60 * 60 * 24 * 30, // 30 days
        sameSite: "lax",
        httpOnly: true,
      });
      return response;
    }

    return NextResponse.json({ success: false, error: "Invalid passcode" }, { status: 401 });
  } catch (error) {
    return NextResponse.json({ success: false, error: "Malformed request" }, { status: 400 });
  }
}
