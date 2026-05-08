import { EntityProfile } from "@/components/profile/EntityProfile";

interface Params {
  params: { name: string };
}

export default function DiseasePage({ params }: Params) {
  const name = decodeURIComponent(params.name);
  return <EntityProfile name={name} kind="Disease" />;
}
