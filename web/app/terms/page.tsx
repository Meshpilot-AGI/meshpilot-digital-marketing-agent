import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms of Service — Mesh Pilot",
  description: "The terms that govern your use of Mesh Pilot.",
};

const UPDATED = "August 29, 2026";

export default function TermsPage() {
  return (
    <main className="relative z-10 mx-auto max-w-3xl px-6 py-16 text-neutral-300">
      <Link href="/" className="text-sm text-neutral-400 hover:text-white">← Back to Mesh Pilot</Link>
      <h1 className="mt-6 font-heading text-4xl text-white">Terms of Service</h1>
      <p className="mt-2 text-sm text-neutral-500">Last updated: {UPDATED}</p>

      <div className="mt-10 space-y-8 leading-relaxed">
        <section>
          <p>
            These Terms of Service (&quot;Terms&quot;) govern your access to and use of Mesh Pilot
            (&quot;Mesh Pilot&quot;, &quot;we&quot;, &quot;us&quot;), including our website, waitlist,
            and services. By joining the waitlist or using the service, you agree to these Terms.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">The service</h2>
          <p className="mt-3">
            Mesh Pilot is an AI marketing agent that helps brands create and, at your direction,
            publish content across connected platforms. Features and availability may change as the
            product evolves.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">Your responsibilities</h2>
          <ul className="mt-3 list-disc space-y-2 pl-6">
            <li>You must provide accurate information and keep your credentials secure.</li>
            <li>You are responsible for the accounts you connect and the content you create or approve for publishing.</li>
            <li>You must have the rights to any content and brand assets you provide, and to publish to the accounts you connect.</li>
            <li>You must comply with the terms and policies of any third-party platform you connect (for example, Meta, Google/YouTube).</li>
          </ul>
        </section>

        <section>
          <h2 className="text-xl text-white">Acceptable use</h2>
          <p className="mt-3">
            You agree not to use Mesh Pilot to create or distribute unlawful, infringing, deceptive,
            or harmful content, to spam, to violate others&apos; rights, or to circumvent platform
            rules or rate limits. We may suspend access for violations.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">Intellectual property</h2>
          <p className="mt-3">
            You retain ownership of the content and brand assets you provide. Mesh Pilot and its
            software, design, and trademarks remain our property. You grant us the limited rights
            needed to operate the service for you.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">Third-party services</h2>
          <p className="mt-3">
            The service integrates with third-party platforms and AI providers. Your use of those
            services is subject to their terms, and we are not responsible for their availability or
            actions.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">Disclaimers</h2>
          <p className="mt-3">
            The service is provided &quot;as is&quot; without warranties of any kind. AI-generated
            output may contain errors; you are responsible for reviewing content before it is
            published.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">Limitation of liability</h2>
          <p className="mt-3">
            To the maximum extent permitted by law, Mesh Pilot will not be liable for indirect,
            incidental, or consequential damages, or for lost profits or data, arising from your use
            of the service.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">Termination</h2>
          <p className="mt-3">
            You may stop using the service at any time. We may suspend or terminate access if you
            violate these Terms or to protect the service.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">Changes</h2>
          <p className="mt-3">
            We may update these Terms from time to time. Continued use after changes take effect
            constitutes acceptance of the updated Terms.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">Contact</h2>
          <p className="mt-3">
            Questions about these Terms? Email{" "}
            <a href="mailto:support@meshpilot.app" className="text-white underline">support@meshpilot.app</a>.
          </p>
        </section>
      </div>

      <div className="mt-12 border-t border-neutral-800 pt-6 text-sm text-neutral-500">
        <Link href="/privacy" className="hover:text-white">Privacy Policy</Link>
      </div>
    </main>
  );
}
