def generate_gnb_config(
    amf_ip,
    n2_ip,
    n3_ip,
    near_ric_ip,
    template_path="gnbe2.conf",
    output_path="gnbe2_generated.conf"
):
    """
    Generates gNB configuration by replacing placeholders in the template.

    Args:
        amf_ip (str): IP address of the AMF.
        n2_ip (str): gNB's N2 interface IP.
        n3_ip (str): gNB's N3 interface IP.
        near_ric_ip (str): IP address of near-RT RIC.
        template_path (str): Path to the gNB config template.
        output_path (str): Path to save the generated config.
    """
    # Read the template
    with open(template_path, "r") as file:
        config = file.read()

    # Replacements
    replacements = {
        "@AMF_IP_ADDRESS@": amf_ip,
        "@N2_IP_ADDRESS@": n2_ip,
        "@N3_IP_ADDRESS@": n3_ip,
        "@NEAR_RIC_IP_ADDRESS@": near_ric_ip
    }

    for placeholder, value in replacements.items():
        config = config.replace(placeholder, value)

    # Write the output
    with open(output_path, "w") as file:
        file.write(config)

    print(f"Generated gNB config saved at: {output_path}")


if __name__ == "__main__":
    AMF_IP = "192.168.70.132"
    N2_IP = "192.168.70.141"
    N3_IP = "192.168.70.141"
    NEAR_RIC_IP = "192.168.70.154"

    generate_gnb_config(
        amf_ip=AMF_IP,
        n2_ip=N2_IP,
        n3_ip=N3_IP,
        near_ric_ip=NEAR_RIC_IP
    )
