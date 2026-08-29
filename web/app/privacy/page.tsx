import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy Policy — Mesh Pilot",
  description: "How Mesh Pilot collects, uses, and protects your information.",
};

const UPDATED = "August 29, 2026";

export default function PrivacyPage() {
  return (
    <main className="relative z-10 mx-auto max-w-3xl px-6 py-16 text-neutral-300">
      <Link href="/" className="text-sm text-neutral-400 hover:text-white">← Back to Mesh Pilot</Link>
      <h1 className="mt-6 font-heading text-4xl text-white">Privacy Policy</h1>
      <p className="mt-2 text-sm text-neutral-500">Last updated: {UPDATED}</p>

      <div className="mt-10 space-y-8 leading-relaxed">
        <section>
          <p>
            This Privacy Policy explains how Mesh Pilot (&quot;Mesh Pilot&quot;, &quot;we&quot;,
            &quot;us&quot;) collects, uses, and shares information when you join our waitlist or use
            our services. Mesh Pilot is an AI marketing agent that helps brands create and publish
            content across social platforms.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">Information we collect</h2>
          <ul className="mt-3 list-disc space-y-2 pl-6">
            <li><strong>Waitlist information.</strong> When you join the waitlist, we collect your email address.</li>
            <li>
              <strong>Account and connected-platform data.</strong> When you use the product, we
              process the credentials and content you connect — for example social accounts
              (Meta / Facebook / Instagram, YouTube), scheduling tools, and media sources — solely
              to operate the features you enable, on a per-brand basis.
            </li>
            <li>
              <strong>Content you provide or generate.</strong> Briefs, scripts, captions, and the
              images or videos generated for your brand.
            </li>
            <li><strong>Usage and technical data.</strong> Basic logs and diagnostics needed to run and secure the service.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-xl text-white">How we use information</h2>
          <ul className="mt-3 list-disc space-y-2 pl-6">
            <li>To provide, operate, and improve the service you request.</li>
            <li>To generate and, when you explicitly enable it, publish content to your connected accounts.</li>
            <li>To communicate with you about the waitlist, updates, and support.</li>
            <li>To secure the service and comply with legal obligations.</li>
          </ul>
          <p className="mt-3">
            We do not sell your personal information, and we do not use data obtained from a
            platform&apos;s API for advertising or to build user profiles unrelated to the service
            you use.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">Platform data (Meta, Google, and others)</h2>
          <p className="mt-3">
            When you connect a platform account (such as Facebook, Instagram, or YouTube), we access
            only the data and permissions required for the features you enable — for example,
            publishing a post you approve. We use that data solely to provide those features and
            retain it only as long as needed. You can disconnect an account at any time, and you may
            request deletion of associated data as described below.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">Service providers</h2>
          <p className="mt-3">
            We rely on trusted third-party processors to run the service, including cloud hosting and
            storage, database, content-delivery, and AI media-generation providers. These providers
            process data only on our behalf and under appropriate safeguards.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">Data retention & security</h2>
          <p className="mt-3">
            We keep information for as long as needed to provide the service and meet legal
            requirements, then delete or anonymize it. We use industry-standard measures — including
            encryption in transit and access controls — to protect your data. No method of
            transmission or storage is completely secure.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">Your rights</h2>
          <p className="mt-3">
            Depending on your location, you may have the right to access, correct, export, or delete
            your personal information, and to withdraw consent. To exercise these rights — including
            removing your email from the waitlist or deleting connected-platform data — contact us at{" "}
            <a href="mailto:support@meshpilot.app" className="text-white underline">support@meshpilot.app</a>.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">Children</h2>
          <p className="mt-3">Mesh Pilot is not directed to children under 13, and we do not knowingly collect their data.</p>
        </section>

        <section>
          <h2 className="text-xl text-white">Changes</h2>
          <p className="mt-3">
            We may update this policy from time to time. Material changes will be reflected by the
            &quot;Last updated&quot; date above.
          </p>
        </section>

        <section>
          <h2 className="text-xl text-white">Contact</h2>
          <p className="mt-3">
            Questions? Email{" "}
            <a href="mailto:support@meshpilot.app" className="text-white underline">support@meshpilot.app</a>.
          </p>
        </section>
      </div>

      <div className="mt-12 border-t border-neutral-800 pt-6 text-sm text-neutral-500">
        <Link href="/terms" className="hover:text-white">Terms of Service</Link>
      </div>
    </main>
  );
}
