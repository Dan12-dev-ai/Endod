import Header from './components/header';
import Hero from './components/hero';
import Bottleneck from './components/bottleneck';
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
      <BuildLab />
      <CloudLab />
      <SocialProof />
      <Pipette />
      <SocialLinks />
      <Footer />
    </>
  );
}
