def generate_du_config(
    f1_du_ip,
    cu_ip,
    near_ric_ip,
    template_path='du.conf',
    output_path='du_generated.conf'
):
    # Load template
    with open(template_path, 'r') as f:
        config = f.read()

    # Define all replacements
    replacements = {
        '@F1_DU_IP_ADDRESS@': f1_du_ip,
        '@CU_IP_ADDRESS@': cu_ip,
        '@NEAR_RIC_IP_ADDRESS@': near_ric_ip
    }

    # Apply replacements
    for placeholder, value in replacements.items():
        config = config.replace(placeholder, value)

    # Write the final config
    with open(output_path, 'w') as f:
        f.write(config)

    print(f"Generated DU config at: {output_path}")


if __name__ == '__main__':
    # Define your DU-specific IP configuration here
    F1_DU_IP = '192.168.70.141'
    CU_IP = '192.168.70.139'
    NEAR_RIC_IP = '192.168.70.154'

    generate_du_config(
        f1_du_ip=F1_DU_IP,
        cu_ip=CU_IP,
        near_ric_ip=NEAR_RIC_IP
    )
