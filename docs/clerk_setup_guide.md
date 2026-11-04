# Clerk Setup & Sandbox Guide

This guide explains how to set up Clerk and build a **sandbox login experience** that is completely isolated from your main application. 

By following this approach, your existing app (and the passcode system) will remain **100% untouched and functional**. You can test the Clerk UI, see how the JWTs work, and only "flip the switch" when you are confident it's ready for primetime.

---

## 1. The Strategy: How to Isolate Clerk

Clerk requires its `<ClerkProvider>` to wrap your application. However, **wrapping the app does not automatically lock it down**. 
Security is enforced by a Next.js `middleware.ts` file. 

To keep Clerk isolated:
1. We will wrap the root layout in `<ClerkProvider>` (harmless on its own).
2. We will NOT use Next.js middleware. Instead, we will use **resource-based auth checks** (`auth().protect()`) exclusively on our test routes (e.g., `/sandbox-protected`). This guarantees all your existing routes (like `/`, `/settings`, `/portfolio`) remain completely unprotected by Clerk.

---

## 2. Initial Setup

### Step A: Create a Clerk Project
1. Go to [Clerk.com](https://clerk.com) and sign up for a free account.
2. Create a new application.
3. Select the authentication methods you want (e.g., Email, Google).
4. Copy your **API Keys** from the dashboard.

### Step B: Install the SDK
Run this command in your `frontend` directory:
```bash
npm install @clerk/nextjs
```

### Step C: Add Environment Variables
Add the keys to your `frontend/.env.local` file:
```env
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...

# Tell Clerk where our custom sandbox routes are
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sandbox-login
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sandbox-signup
```

---

## 3. Implementation Steps

### Step 1: Wrap the Root Layout
Edit `frontend/app/layout.tsx` to include the `ClerkProvider`. This just makes Clerk *available* to the app, it doesn't break anything.

```tsx
import { ClerkProvider } from '@clerk/nextjs'
// ... your other imports

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body>
          {/* Your existing ThemeProvider and Layout continue to work as normal */}
          {children}
        </body>
      </html>
    </ClerkProvider>
  )
}
```

### Step 2: Skip Middleware
Clerk has deprecated middleware-based protection (`createRouteMatcher`). We will skip middleware completely and protect our route directly inside the page component in Step 4.

### Step 3: Build the Sandbox Login Pages
Create these folders and files to render Clerk's beautiful pre-built components.

**`frontend/app/sandbox-login/[[...sandbox-login]]/page.tsx`**
```tsx
import { SignIn } from "@clerk/nextjs";

export default function SandboxLoginPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a]">
      <SignIn path="/sandbox-login" routing="path" signUpUrl="/sandbox-signup" />
    </div>
  );
}
```

**`frontend/app/sandbox-signup/[[...sandbox-signup]]/page.tsx`**
```tsx
import { SignUp } from "@clerk/nextjs";

export default function SandboxSignUpPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a]">
      <SignUp path="/sandbox-signup" routing="path" signInUrl="/sandbox-login" />
    </div>
  );
}
```

### Step 4: Build a Sandbox Dashboard to test the Token
Create a dummy protected page to verify it worked and see what the backend token looks like.

**`frontend/app/sandbox-protected/page.tsx`**
```tsx
import { UserButton } from "@clerk/nextjs";
import { auth, currentUser } from "@clerk/nextjs/server";

export default async function SandboxProtectedPage() {
  // Protect this page dynamically (resource-based auth)
  const { getToken, protect } = auth();
  protect();

  const user = await currentUser();
  
  // This is the JWT token you will eventually send to FastAPI!
  const token = await getToken();

  return (
    <div className="min-h-screen p-8 text-white bg-[#0a0a0a]">
      <div className="flex justify-between items-center mb-8 border-b border-gray-800 pb-4">
        <h1 className="text-2xl font-bold text-brand-gold">Clerk Sandbox</h1>
        <UserButton afterSignOutUrl="/" />
      </div>

      <div className="space-y-4">
        <p>Welcome, {user?.primaryEmailAddress?.emailAddress}!</p>
        <p>Your unique User ID is: <code className="bg-gray-800 p-1 rounded">{user?.id}</code></p>
        
        <div className="mt-8">
          <h3 className="text-brand-gold mb-2">Backend JWT Token (Preview):</h3>
          <pre className="bg-gray-900 p-4 rounded text-xs overflow-x-auto text-gray-400">
            {token}
          </pre>
        </div>
      </div>
    </div>
  );
}
```

---

## 4. How to Transition to "Primetime"

Once you have played with `/sandbox-login`, customised the colors in the Clerk dashboard, and are ready to deploy it to the whole app:

1. Add `auth().protect()` to the pages you want to lock down (or `layout.tsx` if you want to lock down a whole folder).
2. Remove your old custom `login` page and passcode cookie logic.
3. Update your frontend API calls to attach the `getToken()` JWT in the `Authorization` header.
4. Add the PyJWT verification middleware to FastAPI to decode that token and extract the user ID.
