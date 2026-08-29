import React from "react";
import type { Metadata } from "next";
import { Cal_Sans as FontHeading, Plus_Jakarta_Sans as FontSans } from "next/font/google";
import "./globals.css";

const fontSans = FontSans({
    subsets: ["latin"],
    variable: "--font-sans"
});

const fontHeading = FontHeading({
    subsets: ["latin"],
    variable: "--font-heading",
    weight: "400"
});

export const metadata: Metadata = {
  title: "Mesh Pilot — Digital Marketing AGI Agent",
  description:
    "Mesh Pilot is an autonomous digital marketing agent that runs 24/7 in the cloud, fully AI-native. It creates, decides, and ships content for your brands around the clock.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body
          className={`${fontSans.variable} ${fontHeading.variable} font-sans antialiased`}
      >
        <div className="bg-pattern"></div>
        {children}
      </body>
    </html>
  );
}
