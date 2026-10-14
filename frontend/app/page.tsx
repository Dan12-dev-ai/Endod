import Header from './components/header';
import Hero from './components/hero';
import Bottleneck from './components/bottleneck';
import VideoShowcase from './components/video-showcase';
import BuildLab from './components/build-lab';
import CloudLab from './components/cloud-lab';
import SocialProof from './components/social-proof';
import Pipette from './components/pipette';
import SocialLinks from './components/social-links';
import Footer from './components/footer';

export default function Home() {
  return (
    <>
      <Header />
      <Hero />
      <Bottleneck />
      <VideoShowcase />
      <BuildLab />
      <CloudLab />
      <SocialProof />
      <Pipette />
      <SocialLinks />
      <Footer />
    </>
  );
}
