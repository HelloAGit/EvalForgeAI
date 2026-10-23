/** @type {import('next').NextConfig} */
module.exports = {
  // Static export: served by the FastAPI backend in the single-image build.
  output: 'export',
  images: { unoptimized: true },
};
