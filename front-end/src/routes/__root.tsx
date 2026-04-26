import { Outlet, Link, createRootRoute, HeadContent, Scripts } from "@tanstack/react-router";

import appCss from "../styles.css?url";

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="max-w-md text-center">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-magenta">Error 404</p>
        <h1 className="mt-4 font-serif text-7xl text-foreground">
          Off the <span className="italic text-gradient-radiant">grid</span>
        </h1>
        <p className="mt-3 text-sm text-muted-foreground">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <div className="mt-8">
          <Link
            to="/"
            className="inline-flex items-center justify-center rounded-full gradient-radiant px-6 py-3 text-sm font-medium text-primary-foreground glow-magenta transition-transform hover:scale-[1.02]"
          >
            Back home
          </Link>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "Helio — Engineering-grade solar in minutes" },
      {
        name: "description",
        content:
          "Upload a roof video, panel photo, and utility bill. Helio designs your solar, battery, and heat pump system — reviewed by a real installer.",
      },
      { name: "author", content: "Helio Energy" },
      { property: "og:title", content: "Helio — Engineering-grade solar in minutes" },
      {
        property: "og:description",
        content:
          "Three files in. A complete solar + heat pump proposal out. No site visit required.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "twitter:site", content: "@Lovable" },
    ],
    links: [
      {
        rel: "stylesheet",
        href: appCss,
      },
    ],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
});

function RootShell({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function RootComponent() {
  return <Outlet />;
}
