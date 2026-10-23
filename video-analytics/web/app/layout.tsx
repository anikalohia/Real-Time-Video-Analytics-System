import "./globals.css";

export const metadata = {
  title: "Video Analytics Dashboard",
  description: "Real-time video analytics",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
